// Client-side cache for the AI Insights drawer summaries.
//
// The backend caches each summary for AI_INSIGHTS_REFRESH_TIMEOUT minutes and
// returns `updated_at`, but the drawer refetches on every mount and the state
// is per-mount — so reopening the drawer (or switching tabs) re-generated the
// same text (seconds of waiting + duplicate LLM cost). This cache keeps the
// last rendered summary per entity/tab/language so a reopen is instant; the
// drawer's existing refresh button runs the query with forceRefresh: true and
// updates both the cache and the timestamp.

export interface InsightsCacheEntry {
  result: string;
  trend?: string | null;
  confidence?: number | null;
  fetchedAt: number; // epoch ms
}

const CACHE = new Map<string, InsightsCacheEntry>();

const key = (entityId: string, tab: string, language: string) =>
  `${entityId}:${tab}:${language}`;

export const insightsCacheGet = (
  entityId: string,
  tab: string,
  language: string,
): InsightsCacheEntry | null => CACHE.get(key(entityId, tab, language)) ?? null;

export const insightsCacheSet = (
  entityId: string,
  tab: string,
  language: string,
  entry: Omit<InsightsCacheEntry, 'fetchedAt'>,
): void => {
  CACHE.set(key(entityId, tab, language), { ...entry, fetchedAt: Date.now() });
};
