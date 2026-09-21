import type Express from 'express';
import nconf from 'nconf';
import { createAuthenticatedContext } from './httpAuthenticatedContext';
import { logApp } from '../config/conf';
import { getHttpClient, getResponseError } from '../utils/http-client';
import { setCookieError } from './httpUtils';
import xtmOneClient from '../modules/xtm/one/xtm-one-client';

// ── opencti-agent proxy (v3) ─────────────────────────────────────────────
// Non-streaming proxy from the authenticated platform to the local
// opencti-agent HTTP API (FastAPI, default http://127.0.0.1:8100).
//
// Authorization model (v3 MVP): any authenticated platform user may ask;
// the agent queries the graph with ITS OWN configured (bench) token, so the
// effective capability is the agent token's, not the asker's. A per-user
// token hand-off is the documented next hardening step — do not expose
// this route beyond localhost deployments until then.
//
// The route is deliberately non-streaming first (matches POST /ask of the
// agent API); an SSE wrapper can follow the postAgentMessageStream pattern.

const AGENT_API_URL = nconf.get('ai:agent_api_url') || 'http://127.0.0.1:8100';
const AGENT_TIMEOUT = 3 * 60 * 1000;

export const postAiAgentAsk = async (req: Express.Request, res: Express.Response) => {
  try {
    const context = await createAuthenticatedContext(req, res, 'chatbot');
    if (!context?.user) {
      res.sendStatus(403);
      return;
    }
    const question = String(req.body?.question ?? '').trim();
    if (question.length < 5 || question.length > 4000) {
      res.status(400).json({ error: 'question must be between 5 and 4000 characters' });
      return;
    }
    const userInitiator = context.user.id;
    logApp.info('AI agent ask', { user: userInitiator, question_length: question.length });
    const httpClient = getHttpClient({
      baseURL: AGENT_API_URL,
      responseType: 'json',
      headers: { 'Content-Type': 'application/json' },
    });
    // session_id passes through so the agent keeps per-session context.
    const payload: Record<string, unknown> = { question };
    if (typeof req.body?.session_id === 'string' && req.body.session_id.length > 0) {
      payload.session_id = req.body.session_id;
    }
    const response = await httpClient.post('/ask', payload, { timeout: AGENT_TIMEOUT });
    res.json(response.data);
  } catch (e: unknown) {
    logApp.error('Error in AI agent proxy', { cause: e });
    const message = (e as Error).message;
    setCookieError(res, message);
    const httpErr = getResponseError(e);
    if (httpErr) {
      const detail = httpErr.data?.detail ?? httpErr.data?.error ?? message;
      res.status(httpErr.status).send({ status: 'error', error: detail });
    } else {
      res.status(503).send({ status: 'error', error: 'opencti-agent API is unreachable' });
    }
  }
};

// ── session passthrough (M2) ─────────────────────────────────────────────
// Thin authenticated passthrough for the chat-session CRUD onto the agent
// (/sessions). Same authorization caveat as /ask above.
const agentSessionProxy = (handler: 'get' | 'post' | 'delete') => {
  return async (req: Express.Request, res: Express.Response) => {
    try {
      const context = await createAuthenticatedContext(req, res, 'chatbot');
      if (!context?.user) {
        res.sendStatus(403);
        return;
      }
      const httpClient = getHttpClient({
        baseURL: AGENT_API_URL,
        responseType: 'json',
        headers: { 'Content-Type': 'application/json' },
      });
      const sid = String(req.params?.sid ?? '');
      const path = sid ? `/sessions/${encodeURIComponent(sid)}` : '/sessions';
      const response = await httpClient[handler](path, req.body ?? {}, { timeout: 30_000 });
      if (response.status === 204 || response.status === 404) {
        res.status(response.status).json(response.data ?? {});
        return;
      }
      res.json(response.data);
    } catch (e: unknown) {
      logApp.error('Error in AI agent session proxy', { cause: e });
      res.status(503).send({ status: 'error', error: 'opencti-agent API is unreachable' });
    }
  };
};

export const postAiAgentSession = agentSessionProxy('post');
export const getAiAgentSessions = agentSessionProxy('get');
export const getAiAgentSession = agentSessionProxy('get');
export const deleteAiAgentSession = agentSessionProxy('delete');

// ── file → STIX extraction (cti.stix_harvester, local mode) ──────────────
// Local equivalent of the XTM One stix_harvester intent: an authenticated
// user uploads a file (raw bytes, ?filename= drives format detection), the
// platform forwards it to the agent's POST /extract_file and returns the
// extraction result including a ready-to-import STIX 2.1 bundle. The
// frontend feeds that bundle into the standard import flow, so validation
// (workbench/draft) and markings behave exactly like a normal import.
// Local-mode only: XTM One keeps its own connector path.
export const isLocalAgentConfigured = (): boolean =>
  !xtmOneClient.isConfigured() && !!nconf.get('ai:agent_api_url');

const AGENT_EXTRACT_MAX_BYTES = 20 * 1024 * 1024;

export const postAiAgentExtractFile = async (req: Express.Request, res: Express.Response) => {
  try {
    if (!isLocalAgentConfigured()) {
      res.status(403).json({ error: 'Local AI agent is not configured' });
      return;
    }
    const context = await createAuthenticatedContext(req, res, 'chatbot');
    if (!context?.user) {
      res.sendStatus(403);
      return;
    }
    const body = req.body;
    if (!Buffer.isBuffer(body) || body.length < 16) {
      res.status(400).json({ error: 'file body is empty' });
      return;
    }
    if (body.length > AGENT_EXTRACT_MAX_BYTES) {
      res.status(413).json({ error: `file too large (max ${AGENT_EXTRACT_MAX_BYTES / (1024 * 1024)} MB)` });
      return;
    }
    const filename = String(req.query?.filename ?? 'file.txt')
      .replace(/[\r\n]/g, '')
      .slice(0, 255) || 'file.txt';
    logApp.info('AI agent file extract', { user: context.user.id, filename, bytes: body.length });
    const httpClient = getHttpClient({
      baseURL: AGENT_API_URL,
      responseType: 'json',
      headers: { 'Content-Type': 'application/octet-stream' },
    });
    const response = await httpClient.post(
      `/extract_file?filename=${encodeURIComponent(filename)}`,
      body,
      { timeout: AGENT_TIMEOUT, maxBodyLength: Infinity, maxContentLength: Infinity },
    );
    res.json(response.data);
  } catch (e: unknown) {
    logApp.error('Error in AI agent file extract', { cause: e });
    const message = (e as Error).message;
    setCookieError(res, message);
    const httpErr = getResponseError(e);
    if (httpErr) {
      const detail = httpErr.data?.detail ?? httpErr.data?.error ?? message;
      res.status(httpErr.status).send({ status: 'error', error: detail });
    } else {
      res.status(503).send({ status: 'error', error: 'opencti-agent API is unreachable' });
    }
  }
};
