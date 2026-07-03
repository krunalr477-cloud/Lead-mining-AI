/**
 * Query key factory — the single place TanStack Query keys are minted so
 * invalidation stays consistent. Keys are readonly tuples for type safety.
 */
export const queryKeys = {
  me: () => ["me"] as const,

  jobs: {
    all: () => ["jobs"] as const,
    list: (filters?: Record<string, unknown>) =>
      ["jobs", "list", filters ?? {}] as const,
    detail: (jobId: string) => ["jobs", "detail", jobId] as const,
    results: (jobId: string, filters?: Record<string, unknown>) =>
      ["jobs", "results", jobId, filters ?? {}] as const,
    events: (jobId: string) => ["jobs", "events", jobId] as const,
  },

  dashboard: {
    all: () => ["dashboard"] as const,
    summary: () => ["dashboard", "summary"] as const,
    funnel: () => ["dashboard", "funnel"] as const,
    sourcePerformance: () => ["dashboard", "source-performance"] as const,
    campaignPerformance: () => ["dashboard", "campaign-performance"] as const,
  },

  companies: {
    all: () => ["companies"] as const,
    list: (filters?: Record<string, unknown>) =>
      ["companies", "list", filters ?? {}] as const,
    detail: (companyId: string) => ["companies", "detail", companyId] as const,
  },

  contacts: {
    all: () => ["contacts"] as const,
    list: (filters?: Record<string, unknown>) =>
      ["contacts", "list", filters ?? {}] as const,
    detail: (contactId: string) => ["contacts", "detail", contactId] as const,
  },

  validation: {
    byJob: (jobId: string) => ["validation", "job", jobId] as const,
  },

  sheets: {
    status: () => ["sheets", "status"] as const,
    events: () => ["sheets", "events"] as const,
  },

  campaigns: {
    all: () => ["campaigns"] as const,
    list: () => ["campaigns", "list"] as const,
    detail: (campaignId: string) => ["campaigns", "detail", campaignId] as const,
  },

  bounces: {
    list: (filters?: Record<string, unknown>) =>
      ["bounces", "list", filters ?? {}] as const,
  },

  exports: {
    list: () => ["exports", "list"] as const,
  },

  settings: {
    all: () => ["settings"] as const,
    audit: (filters?: Record<string, unknown>) =>
      ["settings", "audit", filters ?? {}] as const,
  },
} as const;
