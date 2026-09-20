import type { ChatPromptValueInterface } from '@langchain/core/prompt_values';
import { ChatMistralAI } from '@langchain/mistralai';
import { AzureChatOpenAI, ChatOpenAI } from '@langchain/openai';
import { Mistral } from '@mistralai/mistralai';
import type { ChatCompletionStreamRequest } from '@mistralai/mistralai/models/components';
import { AuthenticationError, AzureOpenAI, OpenAI } from 'openai';
import dns from 'node:dns';
import conf, { booleanConf, BUS_TOPICS, logApp } from '../config/conf';
import { UnknownError, UnsupportedError } from '../config/errors';
import { OutputSchema } from '../modules/ai/ai-nlq-schema';
import type { Output } from '../modules/ai/ai-nlq-schema';
import { AI_BUS } from '../modules/ai/ai-types';
import { resolveAiRuntimeConfig } from '../modules/ai/ai-config';
import type { AiRuntimeConfig } from '../modules/ai/ai-config';
import type { AuthUser } from '../types/user';
import { truncate } from '../utils/format';
import { notify } from './redis';
import { isEmptyField } from './utils';

// Some LLM endpoints (e.g. api.z.ai) resolve to IPv6-only while the host may
// have no IPv6 route; undici/fetch then hangs instead of falling back.
dns.setDefaultResultOrder('ipv4first');

interface AiClients {
  cfg: AiRuntimeConfig;
  client: Mistral | OpenAI | AzureOpenAI | null;
  nlqChat: ChatOpenAI | ChatMistralAI | AzureChatOpenAI | null;
}

// Clients are (re)built from the resolved runtime configuration (registry
// active provider, or the ai:* environment configuration) and cached until
// that configuration changes.
const buildClients = (cfg: AiRuntimeConfig): { client: AiClients['client']; nlqChat: AiClients['nlqChat'] } => {
  if (!booleanConf('ai:enabled', false) || isEmptyField(cfg.token)) {
    return { client: null, nlqChat: null };
  }
  switch (cfg.type) {
    case 'mistralai': {
      const client = new Mistral({
        serverURL: isEmptyField(cfg.endpoint) ? undefined : cfg.endpoint,
        apiKey: cfg.token ?? undefined,
      });

      let nlqChat: ChatOpenAI | ChatMistralAI;
      if ((cfg.endpoint ?? '').includes('https://api.mistral.ai')) {
        // Official MistralAI API
        nlqChat = new ChatMistralAI({
          model: cfg.model ?? undefined,
          apiKey: cfg.token ?? undefined,
          temperature: 0,
        });
      } else {
        // Mistral model deployed via vLLM (OpenAI-compatible)
        nlqChat = new ChatOpenAI({
          model: cfg.model ?? undefined,
          apiKey: cfg.token ?? undefined,
          temperature: 0,
          configuration: {
            baseURL: `${cfg.endpoint}/v1`,
          },
        });
      }
      return { client, nlqChat };
    }

    case 'openai': {
      const client = new OpenAI({
        apiKey: cfg.token ?? undefined,
        ...(isEmptyField(cfg.endpoint) ? {} : { baseURL: cfg.endpoint }),
        // Pin the global fetch implementation: esbuild-bundled SDK may otherwise
        // pick its undici-based transport, which is flaky in some environments
        // (e.g. IPv6-only DNS answers on hosts without an IPv6 route).
        fetch: ((input: any, init?: any) => globalThis.fetch(input, init)) as any,
        maxRetries: 4,
        timeout: 180000,
      });

      const nlqChat = new ChatOpenAI({
        model: cfg.model ?? undefined,
        apiKey: cfg.token ?? undefined,
        temperature: 0,
        configuration: {
          baseURL: cfg.endpoint || undefined,
        },
      });
      return { client, nlqChat };
    }

    case 'azureopenai': {
      const client = new AzureOpenAI({
        apiKey: cfg.token ?? undefined,
        ...(isEmptyField(cfg.endpoint) ? {} : { baseURL: cfg.endpoint }),
        ...(isEmptyField(conf.get('ai:version')) ? {} : { apiVersion: conf.get('ai:version') }),
      });

      const nlqChat = new AzureChatOpenAI({
        azureOpenAIApiKey: cfg.token ?? undefined,
        azureOpenAIApiVersion: conf.get('ai:version'),
        azureOpenAIApiInstanceName: conf.get('ai:ai_azure_instance'),
        azureOpenAIApiDeploymentName: conf.get('ai:ai_azure_deployment'),
        temperature: 0,
      });
      return { client, nlqChat };
    }

    default:
      throw UnsupportedError('Not supported AI type (currently support: mistralai, openai, azureopenai)', { type: cfg.type });
  }
};

let clientsCache: { key: string; clients: AiClients } | null = null;

const getAiClients = async (): Promise<AiClients> => {
  const cfg = await resolveAiRuntimeConfig();
  const key = JSON.stringify({
    enabled: booleanConf('ai:enabled', false),
    id: cfg.id,
    type: cfg.type,
    endpoint: cfg.endpoint,
    token: cfg.token,
    model: cfg.model,
    maxTokens: cfg.maxTokens,
    version: conf.get('ai:version'),
    azure_instance: conf.get('ai:ai_azure_instance'),
    azure_deployment: conf.get('ai:ai_azure_deployment'),
  });
  if (!clientsCache || clientsCache.key !== key) {
    clientsCache = { key, clients: { cfg, ...buildClients(cfg) } };
  }
  return clientsCache.clients;
};

const badAiConfigError = (cfg: AiRuntimeConfig, forNlq = false) => UnsupportedError(forNlq ? 'Incorrect AI configuration for NLQ' : 'Incorrect AI configuration', {
  enabled: booleanConf('ai:enabled', false),
  type: cfg.type,
  endpoint: cfg.endpoint,
  model: cfg.model,
});

// Query MistralAI (Streaming)
export const queryMistralAi = async (busId: string | null, systemMessage: string, userMessage: string, user: AuthUser) => {
  const { cfg, client } = await getAiClients();
  if (!client) {
    throw badAiConfigError(cfg);
  }
  try {
    logApp.debug('[AI] Querying MistralAI with prompt', { questionStart: userMessage.substring(0, 100) });
    const request: ChatCompletionStreamRequest = {
      model: cfg.model ?? '',
      temperature: 0,
      messages: [
        { role: 'system', content: systemMessage },
        { role: 'user', content: truncate(userMessage, cfg.maxTokens ?? undefined, false) },
      ],
    };
    const response = await (client as Mistral)?.chat.stream(request);
    let content = '';
    if (response) {
      for await (const chunk of response) {
        // eslint-disable-next-line no-null/no-null
        if (chunk.data.choices[0].delta.content != null) {
          const streamText = chunk.data.choices[0].delta.content;
          content += streamText;
          if (busId !== null) {
            await notify(BUS_TOPICS[AI_BUS].EDIT_TOPIC, { bus_id: busId, content }, user);
          }
        }
      }
      return content;
    }
    logApp.error('[AI] No response from MistralAI', { busId, systemMessage, userMessage });
    return 'No response from MistralAI';
  } catch (err) {
    logApp.error('[AI] Cannot query MistralAI', { cause: err });
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-expect-error
    return `An error occurred: ${err.toString()}`;
  }
};

// Query OpenAI (Streaming)
export const queryChatGpt = async (busId: string | null, developerMessage: string, userMessage: string, user: AuthUser) => {
  const { cfg, client } = await getAiClients();
  if (!client) {
    throw badAiConfigError(cfg);
  }
  try {
    logApp.info('[AI] Querying OpenAI with prompt', { type: cfg.type, provider: cfg.id, model: cfg.model });
    const response = await (client as OpenAI)?.chat.completions.create({
      model: cfg.model ?? '',
      messages: [
        { role: 'system', content: developerMessage },
        { role: 'user', content: truncate(userMessage, cfg.maxTokens ?? undefined, false) },
      ],
      stream: true,
    });
    let content = '';
    if (response) {
      // eslint-disable-next-line no-restricted-syntax
      for await (const chunk of response) {
        // eslint-disable-next-line no-null/no-null
        if (chunk.choices[0]?.delta.content != null) {
          const streamText = chunk.choices[0].delta.content;
          content += streamText;
          if (busId !== null) {
            await notify(BUS_TOPICS[AI_BUS].EDIT_TOPIC, { bus_id: busId, content }, user);
          }
        }
      }
      return content;
    }
    logApp.error('[AI] No response from OpenAI', { busId, developerMessage, userMessage });
    return 'No response from OpenAI';
  } catch (err) {
    const dbg = err as { cause?: unknown };
    const chain: unknown[] = [];
    let cur: unknown = dbg.cause;
    for (let i = 0; i < 4 && cur; i += 1) {
      const c = cur as { message?: string; code?: string; name?: string; cause?: unknown };
      chain.push({ name: c.name, code: c.code, message: c.message });
      cur = c.cause;
    }
    logApp.error('[AI][DEBUG] OpenAI failure', { chain: JSON.stringify(chain) });
    logApp.error('[AI] Cannot query OpenAI', { cause: err });
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-expect-error
    return `An error occurred: ${err.toString()}`;
  }
};

// Generic AI Query Handler
export const queryAi = async (busId: string | null, developerMessage: string | null, userMessage: string, user: AuthUser) => {
  const finalDeveloperMessage = developerMessage || 'You are an assistant helping a cyber threat intelligence analyst to better understand cyber threat intelligence data.';
  const { cfg } = await getAiClients();
  switch (cfg.type) {
    case 'mistralai':
      return queryMistralAi(busId, finalDeveloperMessage, userMessage, user);
    case 'azureopenai':
    case 'openai':
      return queryChatGpt(busId, finalDeveloperMessage, userMessage, user);
    default:
      throw UnsupportedError('Not supported AI type', { type: cfg.type });
  }
};

// NLQ AI Query — structured output via OpenAI-compatible tool calling
// (LangChain's withStructuredOutput hangs on some OpenAI-compatible gateways,
// e.g. z.ai; the raw SDK tool-call path is reliable and returns the same
// zod-validated Output).
export const queryNLQAi = async (promptValue: ChatPromptValueInterface) => {
  const { cfg, client, nlqChat } = await getAiClients();
  const nlqBadAiConfigError = badAiConfigError(cfg, true);
  if (!nlqChat || !client) {
    throw nlqBadAiConfigError;
  }

  // NLQ usage telemetry is counted at the feature entry point
  // (generateNLQresponse in ai-domain) so it stays backend-agnostic.

  logApp.info('[NLQ] Querying AI model for structured output', { provider: cfg.id, model: cfg.model });
  try {
    if (cfg.type === 'openai') {
      // The NLQ prompt only carries plain text roles (human/ai/system); anything
      // else falls back to 'user' so the payload matches ChatCompletionMessageParam.
      const roleMap: Record<string, 'user' | 'assistant' | 'system'> = { human: 'user', ai: 'assistant', system: 'system' };
      const messages: OpenAI.Chat.ChatCompletionMessageParam[] = promptValue.messages.map((m) => ({
        role: roleMap[m._getType() as string] ?? 'user',
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
      }));
      // The NLQ prompt (system rules + few-shot examples) already teaches the
      // exact output JSON shape; json_object mode is far more reliable on
      // OpenAI-compatible gateways than a complex anyOf tool schema.
      const response = await (client as OpenAI).chat.completions.create({
        model: cfg.model ?? '',
        messages,
        response_format: { type: 'json_object' },
        temperature: 0,
        max_tokens: 16000,
      });
      const content = response.choices?.[0]?.message?.content ?? '{}';
      // Some models wrap the payload ("{"success":true,"data":{…}}") — unwrap common envelopes.
      let candidate: unknown = JSON.parse(content);
      if (typeof candidate === 'object' && candidate !== null && 'data' in (candidate as object) && !('filters' in (candidate as object))) {
        candidate = (candidate as { data: unknown }).data;
      }
      const parseWithSalvage = (payload: unknown): Output => {
        try {
          return OutputSchema.parse(payload);
        } catch {
          // drop invalid filter items, keep the valid ones (better partial than nothing)
          const obj = (typeof payload === 'object' && payload !== null ? payload : {}) as { mode?: string; filters?: unknown[] };
          const itemSchema = (OutputSchema as unknown as { shape: { filters: { element: { safeParse: (v: unknown) => { success: boolean } } } } }).shape.filters.element;
          const filters = (obj.filters ?? []).filter((f) => itemSchema.safeParse(f).success);
          return OutputSchema.parse({ mode: obj.mode === 'or' ? 'or' : 'and', filters });
        }
      };
      try {
        return parseWithSalvage(candidate);
      } catch (e) {
        // one self-repair round: show the model its invalid JSON + the validation errors
        const repair = await (client as OpenAI).chat.completions.create({
          model: cfg.model ?? '',
          messages: [
            ...messages,
            { role: 'assistant', content: String(content) },
            { role: 'user', content: `Your previous JSON was invalid: ${String(e).slice(0, 500)}. Return the corrected JSON only, same required shape.` },
          ],
          response_format: { type: 'json_object' },
          temperature: 0,
          max_tokens: 16000,
        });
        let repaired: unknown = JSON.parse(repair.choices?.[0]?.message?.content ?? '{}');
        if (typeof repaired === 'object' && repaired !== null && 'data' in (repaired as object) && !('filters' in (repaired as object))) {
          repaired = (repaired as { data: unknown }).data;
        }
        return parseWithSalvage(repaired);
      }
    }
    return await nlqChat.withStructuredOutput<Output>(OutputSchema).invoke(promptValue);
  } catch (err) {
    if (err instanceof AuthenticationError) {
      throw nlqBadAiConfigError;
    }
    throw UnknownError('Error when calling the NLQ model', { cause: err, error_message: String(err).slice(0, 500), promptValue });
  }
};
