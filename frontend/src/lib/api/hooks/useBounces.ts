"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { BounceRow, BouncesFilters } from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/** GET /bounces — bounces + replies. [] on 404/501. */
export function useBounces(filters: BouncesFilters = {}) {
  return useQuery<BounceRow[]>({
    queryKey: queryKeys.bounces.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/bounces", {
        params: { query: cleanParams(filters) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load bounces (${response.status})`);
      }
      return data;
    },
  });
}

/**
 * POST /bounces/poll — trigger an on-demand Gmail inbox poll. Invalidates the
 * bounce list, contacts, suppressions, and dashboard so status updates reflect.
 */
export function usePollBounces() {
  const qc = useQueryClient();
  return useMutation<
    { detected: number; bounces: number; replies: number },
    Error,
    void
  >({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/v1/bounces/poll");
      if (!response.ok || !data) {
        throw new Error(`Failed to poll bounces (${response.status})`);
      }
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.bounces.all() });
      qc.invalidateQueries({ queryKey: queryKeys.suppressions.all() });
      qc.invalidateQueries({ queryKey: queryKeys.contacts.all() });
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.all() });
    },
  });
}
