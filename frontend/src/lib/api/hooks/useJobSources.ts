"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { SourceRunSummary } from "../schema";

/**
 * GET /jobs/{id}/sources — aggregated per-source activity for the Pipeline
 * Activity panel (runs / found→imported / retries / last error per source).
 */
export function useJobSources(
  jobId: string | null | undefined,
  refetchIntervalMs: number | false = false,
) {
  return useQuery<SourceRunSummary[] | null>({
    enabled: !!jobId,
    queryKey: queryKeys.jobs.sources(jobId ?? ""),
    refetchInterval: refetchIntervalMs,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/jobs/{job_id}/sources", {
        params: { path: { job_id: jobId ?? "" } },
      });
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load source activity (${response.status})`);
      }
      return data;
    },
  });
}
