import type Express from 'express';
import nconf from 'nconf';
import { createAuthenticatedContext } from './httpAuthenticatedContext';
import { logApp } from '../config/conf';
import { getHttpClient, getResponseError } from '../utils/http-client';
import { setCookieError } from './httpUtils';

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
