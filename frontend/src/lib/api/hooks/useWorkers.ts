"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { WorkersHealth } from "../schema";

/**
 * GET /workers/health — short-timeout Celery ping. `up: false` is a normal
 * answer (a queued job stays queued until a worker starts), never an error.
 */
export function useWorkersHealth(refetchIntervalMs: number | false = 60_000) {
  return useQuery<WorkersHealth | null>({
    queryKey: queryKeys.workers.health(),
    refetchInterval: refetchIntervalMs,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/workers/health");
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load worker health (${response.status})`);
      }
      return data;
    },
  });
}
