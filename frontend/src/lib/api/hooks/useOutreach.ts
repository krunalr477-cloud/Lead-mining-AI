"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { OutreachQueueFilters, OutreachQueueRow } from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/**
 * GET /outreach — global outreach queue (all campaigns), filterable by
 * campaign. Returns [] on 404/501 so the screen degrades to an EmptyState when
 * no queue endpoint exists yet.
 */
export function useOutreachQueue(filters: OutreachQueueFilters = {}) {
  return useQuery<OutreachQueueRow[]>({
    queryKey: queryKeys.outreach.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/outreach", {
        params: { query: cleanParams(filters) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load outreach queue (${response.status})`);
      }
      return data;
    },
  });
}
