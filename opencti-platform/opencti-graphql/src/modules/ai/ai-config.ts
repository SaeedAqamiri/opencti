import conf, { logApp } from '../../config/conf';
import { FunctionalError } from '../../config/errors';
import { loadEntity } from '../../database/middleware';
import { isEmptyField, isNotEmptyField } from '../../database/utils';
import { ENTITY_TYPE_SETTINGS } from '../../schema/internalObject';
import { generateInternalId } from '../../schema/identifier';
import type { BasicStoreEntity } from '../../types/store';
import { executionContext, SYSTEM_USER } from '../../utils/access';

// Settings entity extended with the AI registry attributes.
export interface BasicStoreEntitySettingsAi extends BasicStoreEntity {
  platform_ai_providers?: unknown[];
  platform_ai_active_provider?: string;
}

// Special provider id meaning "use the environment configuration (ai:* conf)"
export const AI_ENV_PROVIDER_ID = 'env';

// Only OpenAI-compatible gateways are supported by the registry.
export interface StoredAiProvider {
  id: string;
  name: string;
  endpoint: string;
  model: string;
  api_key?: string;
}

export interface AiRuntimeConfig {
  // 'env' when the environment configuration is active, else the provider id
  id: string;
  type: string;
  endpoint: string | null;
  token: string | null;
  model: string | null;
  maxTokens: number | null;
}

// Builtin presets (templates without API keys, the key is provided by the admin).
export const AI_PROVIDER_PRESETS: { id: string; name: string; endpoint: string; model: string }[] = [
  { id: 'avalai-deepseek-v4-1-flash', name: 'AvalAI · DeepSeek v4.1 Flash', endpoint: 'https://api.avalai.ir/v1', model: 'deepseek-v4.1-flash' },
  { id: 'zai-glm-5-3-flash', name: 'Z.AI · GLM 5.3 Flash', endpoint: 'https://api.z.ai/api/coding/paas/v4', model: 'glm-5.3-flash' },
];

const isFilledString = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0;

const envRuntimeConfig = (): AiRuntimeConfig => ({
  id: AI_ENV_PROVIDER_ID,
  type: conf.get('ai:type') ?? 'openai',
  endpoint: isEmptyField(conf.get('ai:endpoint')) ? null : String(conf.get('ai:endpoint')),
  token: isEmptyField(conf.get('ai:token')) ? null : String(conf.get('ai:token')),
  model: isEmptyField(conf.get('ai:model')) ? null : String(conf.get('ai:model')),
  maxTokens: isEmptyField(conf.get('ai:max_tokens')) ? null : Number(conf.get('ai:max_tokens')),
});

const normalizeStoredProvider = (p: Record<string, unknown>): StoredAiProvider | null => {
  if (!p || typeof p !== 'object' || !isFilledString(p.id) || !isFilledString(p.endpoint) || !isFilledString(p.model)) {
    return null;
  }
  return {
    id: p.id,
    name: isFilledString(p.name) ? p.name : p.model,
    endpoint: p.endpoint,
    model: p.model,
    ...(isFilledString(p.api_key) ? { api_key: p.api_key } : {}),
  };
};

interface AiRegistry {
  providers: StoredAiProvider[];
  activeId: string | null;
}

const loadAiRegistry = async (): Promise<AiRegistry> => {
  const context = executionContext('ai_config');
  const settings = await loadEntity<BasicStoreEntitySettingsAi>(context, SYSTEM_USER, [ENTITY_TYPE_SETTINGS]);
  const rawProviders = Array.isArray(settings?.platform_ai_providers) ? settings.platform_ai_providers : [];
  const providers = rawProviders
    .map((p) => normalizeStoredProvider(p as Record<string, unknown>))
    .filter((p): p is StoredAiProvider => p !== null);
  const activeId = isFilledString(settings?.platform_ai_active_provider) ? settings.platform_ai_active_provider : null;
  return { providers, activeId };
};

// Registry view resolved against an already-loaded settings entity (no extra ES read).
export const resolveAiRuntimeFromSettings = (settings?: BasicStoreEntitySettingsAi): AiRuntimeConfig => {
  const activeId = isFilledString(settings?.platform_ai_active_provider) ? settings.platform_ai_active_provider : null;
  if (isNotEmptyField(activeId) && activeId !== AI_ENV_PROVIDER_ID) {
    const rawProviders = Array.isArray(settings?.platform_ai_providers) ? settings.platform_ai_providers : [];
    const provider = rawProviders
      .map((p) => normalizeStoredProvider(p as Record<string, unknown>))
      .find((p) => p !== null && p.id === activeId);
    if (provider) {
      return {
        id: provider.id,
        type: 'openai', // registry providers are OpenAI-compatible by construction
        endpoint: provider.endpoint,
        token: provider.api_key ?? null,
        model: provider.model,
        maxTokens: isEmptyField(conf.get('ai:max_tokens')) ? null : Number(conf.get('ai:max_tokens')),
      };
    }
    logApp.warn('[AI-CONFIG] Active AI provider not found in registry, falling back to environment configuration', { active_id: activeId });
  }
  return envRuntimeConfig();
};

// Resolve the effective AI configuration: registry active provider, else environment.
const RESOLVE_TTL_MS = 10_000;
let resolveCache: { at: number; config: AiRuntimeConfig } | null = null;

export const resetAiRuntimeConfigCache = () => {
  resolveCache = null;
};

export const resolveAiRuntimeConfig = async (): Promise<AiRuntimeConfig> => {
  if (resolveCache && Date.now() - resolveCache.at < RESOLVE_TTL_MS) {
    return resolveCache.config;
  }
  let config: AiRuntimeConfig;
  try {
    const context = executionContext('ai_config');
    const settings = await loadEntity<BasicStoreEntitySettingsAi>(context, SYSTEM_USER, [ENTITY_TYPE_SETTINGS]);
    config = resolveAiRuntimeFromSettings(settings);
  } catch (e) {
    logApp.warn('[AI-CONFIG] Unable to resolve AI registry, falling back to environment configuration', { cause: e });
    config = envRuntimeConfig();
  }
  resolveCache = { at: Date.now(), config };
  return config;
};

// Stored providers as a plain list (API keys included — internal use only).
export const readStoredAiProviders = async (): Promise<StoredAiProvider[]> => {
  try {
    return (await loadAiRegistry()).providers;
  } catch (e) {
    logApp.warn('[AI-CONFIG] Unable to read AI providers registry', { cause: e });
    return [];
  }
};

// Public (GraphQL) view — never exposes the API key itself.
export interface PublicAiProvider {
  id: string;
  name: string;
  endpoint: string;
  model: string;
  api_key_set: boolean;
}

export const toPublicAiProvider = (provider: StoredAiProvider): PublicAiProvider => ({
  id: provider.id,
  name: provider.name,
  endpoint: provider.endpoint,
  model: provider.model,
  api_key_set: isNotEmptyField(provider.api_key),
});

export const envPublicAiProvider = (): PublicAiProvider => ({
  id: AI_ENV_PROVIDER_ID,
  name: 'Environment configuration',
  endpoint: String(conf.get('ai:endpoint') ?? ''),
  model: String(conf.get('ai:model') ?? ''),
  api_key_set: isNotEmptyField(conf.get('ai:token')),
});

// Validate a provider mutation input; throws FunctionalError on invalid payload.
export const validateAiProviderInput = (input: {
  name?: unknown;
  endpoint?: unknown;
  model?: unknown;
  api_key?: unknown;
}): { name: string; endpoint: string; model: string; api_key?: string } => {
  const name = isFilledString(input?.name) ? input.name.trim() : '';
  const endpoint = isFilledString(input?.endpoint) ? input.endpoint.trim() : '';
  const model = isFilledString(input?.model) ? input.model.trim() : '';
  if (!name || !endpoint || !model) {
    throw FunctionalError('AI provider name, endpoint and model are required', { name, endpoint, model });
  }
  if (!/^https?:\/\//i.test(endpoint)) {
    throw FunctionalError('AI provider endpoint must be an http(s) URL', { endpoint });
  }
  const api_key = isFilledString(input?.api_key) ? input.api_key.trim() : '';
  return { name, endpoint, model, ...(api_key ? { api_key } : {}) };
};

export const buildStoredAiProvider = (input: { name?: unknown; endpoint?: unknown; model?: unknown; api_key?: unknown }): StoredAiProvider => ({
  id: generateInternalId(),
  ...validateAiProviderInput(input),
});
