"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type {
  Job,
  JobCreate,
  JobListItem,
  JobResults,
  JobsFilters,
} from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/** GET /jobs — bare array. 404/501 resolves to [] so screens show EmptyState. */
export function useJobs(filters: JobsFilters = {}) {
  return useQuery<JobListItem[]>({
    queryKey: queryKeys.jobs.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/jobs", {
        params: { query: cleanParams(filters) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load jobs (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /jobs/{id} — full record. */
export function useJob(jobId: string | null | undefined) {
  return useQuery<Job>({
    enabled: !!jobId,
    queryKey: queryKeys.jobs.detail(jobId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/jobs/{job_id}", {
        params: { path: { job_id: jobId! } },
      });
      if (!response.ok || !data) {
        throw new Error(`Failed to load job (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /jobs/{id}/results — companies + totals envelope. */
export function useJobResults(jobId: string | null | undefined) {
  return useQuery<JobResults>({
    enabled: !!jobId,
    queryKey: queryKeys.jobs.results(jobId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/jobs/{job_id}/results",
        { params: { path: { job_id: jobId! } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to load job results (${response.status})`);
      }
      return data;
    },
  });
}

/** POST /jobs — create. Invalidates the jobs list on success. */
export function useCreateJob() {
  const qc = useQueryClient();
  return useMutation<Job, Error, JobCreate>({
    mutationFn: async (body) => {
      const { data, response } = await api.POST("/api/v1/jobs", { body });
      if (!response.ok || !data) {
        throw new Error(`Failed to create job (${response.status})`);
      }
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.jobs.all() });
    },
  });
}

function makeJobAction(action: "start" | "pause" | "cancel") {
  return function useJobAction() {
    const qc = useQueryClient();
    return useMutation<Job, Error, string>({
      mutationFn: async (jobId) => {
        const { data, response } = await api.POST(
          `/api/v1/jobs/{job_id}/${action}` as "/api/v1/jobs/{job_id}/start",
          { params: { path: { job_id: jobId } } },
        );
        if (!response.ok || !data) {
          throw new Error(`Failed to ${action} job (${response.status})`);
        }
        return data;
      },
      onSuccess: (job) => {
        qc.setQueryData(queryKeys.jobs.detail(job.id), job);
        qc.invalidateQueries({ queryKey: queryKeys.jobs.all() });
      },
    });
  };
}

export const useStartJob = makeJobAction("start");
export const usePauseJob = makeJobAction("pause");
export const useCancelJob = makeJobAction("cancel");
