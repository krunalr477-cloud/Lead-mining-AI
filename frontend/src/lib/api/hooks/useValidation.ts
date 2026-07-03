"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { ValidationRow, ValidationRunRequest } from "../schema";

export interface ValidationRowsFilters extends Record<string, unknown> {
  limit?: number;
  offset?: number;
}

/** GET /validation/{job_id} — stage-column rows for a job. */
export function useValidationRows(
  jobId: string | null | undefined,
  filters: ValidationRowsFilters = {},
) {
  return useQuery<ValidationRow[]>({
    enabled: !!jobId,
    queryKey: queryKeys.validation.byJob(jobId ?? "", filters),
    queryFn: async () => {
      const query: Record<string, unknown> = {};
      if (filters.limit != null) query.limit = filters.limit;
      if (filters.offset != null) query.offset = filters.offset;
      const { data, response } = await api.GET("/api/v1/validation/{job_id}", {
        params: { path: { job_id: jobId! }, query },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load validation rows (${response.status})`);
      }
      return data;
    },
  });
}

/**
 * POST /validation/run — re-run validation for a set of contacts/email
 * candidates. Invalidates any validation + contact caches on success.
 */
export function useRevalidate() {
  const qc = useQueryClient();
  return useMutation<ValidationRow[], Error, ValidationRunRequest>({
    mutationFn: async (body) => {
      const { data, response } = await api.POST("/api/v1/validation/run", {
        body,
      });
      if (!response.ok || !data) {
        throw new Error(`Failed to run validation (${response.status})`);
      }
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["validation"] });
      qc.invalidateQueries({ queryKey: queryKeys.contacts.all() });
    },
  });
}
