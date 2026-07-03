"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type {
  CampaignPerformance,
  DashboardSummary,
  Funnel,
  SourcePerformance,
} from "../schema";

/** GET /dashboard/summary — headline metrics. null on 404/501. */
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

/** GET /dashboard/funnel — { stages: [{stage, count}] }. */
export function useFunnel() {
  return useQuery<Funnel | null>({
    queryKey: queryKeys.dashboard.funnel(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/dashboard/funnel");
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load funnel (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /dashboard/source-performance — per-source run stats. */
export function useSourcePerformance() {
  return useQuery<SourcePerformance[]>({
    queryKey: queryKeys.dashboard.sourcePerformance(),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/dashboard/source-performance",
      );
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load source performance (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /dashboard/campaign-performance — per-campaign send stats. */
export function useCampaignPerformance() {
  return useQuery<CampaignPerformance[]>({
    queryKey: queryKeys.dashboard.campaignPerformance(),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/dashboard/campaign-performance",
      );
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(
          `Failed to load campaign performance (${response.status})`,
        );
      }
      return data;
    },
  });
}
