"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { DashboardSummary } from "../schema";

/**
 * Placeholder dashboard summary hook returning the typed DashboardSummary
 * shape. Resolves to null on not-yet-implemented endpoints.
 */
export function useDashboardSummary() {
  return useQuery<DashboardSummary | null>({
    queryKey: queryKeys.dashboard.summary(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/dashboard/summary");
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load dashboard (${response.status})`);
      }
      return data;
    },
  });
}
