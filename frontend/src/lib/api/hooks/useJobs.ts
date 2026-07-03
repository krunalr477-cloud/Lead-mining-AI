"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { Job, Paginated } from "../schema";

export interface JobsFilters extends Record<string, unknown> {
  status?: string;
  search?: string;
  page?: number;
}

/**
 * Placeholder jobs list hook. Returns the typed Paginated<Job> shape. Until the
 * backend endpoint is live, a 404/501 resolves to an empty page rather than
 * erroring, so screens render their EmptyState.
 */
export function useJobs(filters: JobsFilters = {}) {
  return useQuery<Paginated<Job>>({
    queryKey: queryKeys.jobs.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/jobs");
      if (response.status === 404 || response.status === 501) {
        return { items: [], total: 0, page: 1, page_size: 25 };
      }
      if (!response.ok || !data) {
        throw new Error(`Failed to load jobs (${response.status})`);
      }
      return data;
    },
  });
}
