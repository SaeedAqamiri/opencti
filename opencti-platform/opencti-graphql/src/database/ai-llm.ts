import type { ChatPromptValueInterface } from '@langchain/core/prompt_values';
import { ChatMistralAI } from '@langchain/mistralai';
import { AzureChatOpenAI, ChatOpenAI } from '@langchain/openai';
import { Mistral } from '@mistralai/mistralai';
import type { ChatCompletionStreamRequest } from '@mistralai/mistralai/models/components';
import { AuthenticationError, AzureOpenAI, OpenAI } from 'openai';
import dns from 'node:dns';
import conf, { BUS_TOPICS, logApp } from '../config/conf';
import { UnknownError, UnsupportedError } from '../config/errors';
import { OutputSchema } from '../modules/ai/ai-nlq-schema';
import type { Output } from '../modules/ai/ai-nlq-schema';
import { AI_BUS } from '../modules/ai/ai-types';
import type { AuthUser } from '../types/user';
import { truncate } from '../utils/format';
import { notify } from './redis';
import { isEmptyField } from './utils';

// Some LLM endpoints (e.g. api.z.ai) resolve to IPv6-only while the host may
// have no IPv6 route; undici/fetch then hangs instead of falling back.
dns.setDefaultResultOrder('ipv4first');

const AI_ENABLED = conf.get('ai:enabled');
const AI_TYPE = conf.get('ai:type');
const AI_ENDPOINT = conf.get('ai:endpoint');
const AI_TOKEN = conf.get('ai:token');
const AI_MODEL = conf.get('ai:model');
const AI_MAX_TOKENS = conf.get('ai:max_tokens');
const AI_VERSION = conf.get('ai:version');
const AI_AZURE_INSTANCE = conf.get('ai:ai_azure_instance');
const AI_AZURE_DEPLOYMENT = conf.get('ai:ai_azure_deployment');

let client: Mistral | OpenAI | AzureOpenAI | null = null;
let nlqChat: ChatOpenAI | ChatMistralAI | AzureChatOpenAI | null = null;
if (AI_ENABLED && AI_TOKEN) {
  switch (AI_TYPE) {
    case 'mistralai':
      client = new Mistral({
        serverURL: isEmptyField(AI_ENDPOINT) ? undefined : AI_ENDPOINT,
        apiKey: AI_TOKEN,
        /* uncomment if you need low level debug on AI
        debugLogger: {
          log: (message, args) => logApp.info(`[AI] log ${message}`, { message }),
          group: (label) => logApp.info(`[AI] group ${label} start.`),
          groupEnd: () => logApp.info('[AI] group end.'),
        } */
      });

      if (AI_ENDPOINT.includes('https://api.mistral.ai')) {
        // Official MistralAI API
        nlqChat = new ChatMistralAI({
          model: AI_MODEL,
          apiKey: AI_TOKEN,
          temperature: 0,
        });
      } else {
        // Mistral model deployed via vLLM (OpenAI-compatible)
        nlqChat = new ChatOpenAI({
          model: AI_MODEL,
          apiKey: AI_TOKEN,
          temperature: 0,
          configuration: {
            baseURL: `${AI_ENDPOINT}/v1`,
          },
        });
      }

      break;

    case 'openai':
      client = new OpenAI({
        apiKey: AI_TOKEN,
        ...(isEmptyField(AI_ENDPOINT) ? {} : { baseURL: AI_ENDPOINT }),
        // Pin the global fetch implementation: esbuild-bundled SDK may otherwise
        // pick its undici-based transport, which is flaky in some environments
        // (e.g. IPv6-only DNS answers on hosts without an IPv6 route).
        fetch: ((input: any, init?: any) => globalThis.fetch(input, init)) as any,
        maxRetries: 4,
        timeout: 180000,
      });

      nlqChat = new ChatOpenAI({
        model: AI_MODEL,
        apiKey: AI_TOKEN,
        temperature: 0,
        configuration: {
          baseURL: AI_ENDPOINT || undefined,
        },
      });

      break;

    case 'azureopenai':
      client = new AzureOpenAI({
        apiKey: AI_TOKEN,
        ...(isEmptyField(AI_ENDPOINT) ? {} : { baseURL: AI_ENDPOINT }),
        ...(isEmptyField(AI_VERSION) ? {} : { apiVersion: AI_VERSION }),
      });

      nlqChat = new AzureChatOpenAI({
        azureOpenAIApiKey: AI_TOKEN,
        azureOpenAIApiVersion: AI_VERSION,
        azureOpenAIApiInstanceName: AI_AZURE_INSTANCE,
        azureOpenAIApiDeploymentName: AI_AZURE_DEPLOYMENT,
        temperature: 0,
      });

      break;

    default:
      throw UnsupportedError('Not supported AI type (currently support: mistralai, openai, azureopenai)', { type: AI_TYPE });
  }
}

// Query MistralAI (Streaming)
export const queryMistralAi = async (busId: string | null, systemMessage: string, userMessage: string, user: AuthUser) => {
  if (!client) {
    throw UnsupportedError('Incorrect AI configuration', { enabled: AI_ENABLED, type: AI_TYPE, endpoint: AI_ENDPOINT, model: AI_MODEL });
  }
  try {
    logApp.debug('[AI] Querying MistralAI with prompt', { questionStart: userMessage.substring(0, 100) });
    const request: ChatCompletionStreamRequest = {
      model: AI_MODEL,
      temperature: 0,
      messages: [
        { role: 'system', content: systemMessage },
        { role: 'user', content: truncate(userMessage, AI_MAX_TOKENS, false) },
      ],
    };
    const response = await (client as Mistral)?.chat.stream(request);
    let content = '';
    if (response) {
      for await (const chunk of response) {
        if (chunk.data.choices[0].delta.content !== undefined) {
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
  if (!client) {
    throw UnsupportedError('Incorrect AI configuration', { enabled: AI_ENABLED, type: AI_TYPE, endpoint: AI_ENDPOINT, model: AI_MODEL });
  }
  try {
    logApp.info('[AI] Querying OpenAI with prompt', { type: AI_TYPE });
    const response = await (client as OpenAI)?.chat.completions.create({
      model: AI_MODEL,
      messages: [
        { role: 'system', content: developerMessage },
        { role: 'user', content: truncate(userMessage, AI_MAX_TOKENS, false) },
      ],
      stream: true,
    });
    let content = '';
    if (response) {
      // eslint-disable-next-line no-restricted-syntax
      for await (const chunk of response) {
        if (chunk.choices[0]?.delta.content !== undefined) {
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
  switch (AI_TYPE) {
    case 'mistralai':
      return queryMistralAi(busId, finalDeveloperMessage, userMessage, user);
    case 'azureopenai':
    case 'openai':
      return queryChatGpt(busId, finalDeveloperMessage, userMessage, user);
    default:
      throw UnsupportedError('Not supported AI type', { type: AI_TYPE });
  }
};

// NLQ AI Query with LangChain's Chat Models
export const queryNLQAi = async (promptValue: ChatPromptValueInterface) => {
  const badAiConfigError = UnsupportedError('Incorrect AI configuration for NLQ', {
    enabled: AI_ENABLED,
    type: AI_TYPE,
    endpoint: AI_ENDPOINT,
    model: AI_MODEL,
  });
  if (!nlqChat) {
    throw badAiConfigError;
  }

  // NLQ usage telemetry is counted at the feature entry point
  // (generateNLQresponse in ai-domain) so it stays backend-agnostic.

  logApp.info('[NLQ] Querying AI model for structured output');
  try {
    return await nlqChat.withStructuredOutput<Output>(OutputSchema).invoke(promptValue);
  } catch (err) {
    if (err instanceof AuthenticationError) {
      throw badAiConfigError;
    }
    throw UnknownError('Error when calling the NLQ model', { cause: err, promptValue });
  }
};
