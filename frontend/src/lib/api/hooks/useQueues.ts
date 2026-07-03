"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { QueueHealth } from "../schema";

/**
 * GET /queues/health — per-queue pending depth + total. Polls on an interval
 * so the ops view stays live without an SSE channel.
 */
export function useQueueHealth(refetchIntervalMs = 5_000) {
  return useQuery<QueueHealth | null>({
    queryKey: queryKeys.queues.health(),
    refetchInterval: refetchIntervalMs,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/queues/health");
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load queue health (${response.status})`);
      }
      return data;
    },
  });
}
