"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type {
  CompaniesFilters,
  Company,
  CompanyDetail,
  CompanyPatch,
} from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/** GET /companies — bare array. */
export function useCompanies(filters: CompaniesFilters = {}) {
  return useQuery<Company[]>({
    queryKey: queryKeys.companies.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/companies", {
        params: { query: cleanParams(filters) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load companies (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /companies/{id} — detail with contacts/sources/hiring_signals. */
export function useCompany(companyId: string | null | undefined) {
  return useQuery<CompanyDetail>({
    enabled: !!companyId,
    queryKey: queryKeys.companies.detail(companyId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/companies/{company_id}",
        { params: { path: { company_id: companyId! } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to load company (${response.status})`);
      }
      return data;
    },
  });
}

export interface PatchCompanyVars {
  companyId: string;
  patch: CompanyPatch;
}

/**
 * PATCH /companies/{id} with an OPTIMISTIC update of the detail cache and any
 * matching list caches. Rolls back on error, invalidates on settle.
 */
export function usePatchCompany() {
  const qc = useQueryClient();
  return useMutation<
    CompanyDetail,
    Error,
    PatchCompanyVars,
    { detailKey: readonly unknown[]; prevDetail?: CompanyDetail; prevLists: [readonly unknown[], Company[]][] }
  >({
    mutationFn: async ({ companyId, patch }) => {
      const { data, response } = await api.PATCH(
        "/api/v1/companies/{company_id}",
        { params: { path: { company_id: companyId } }, body: patch },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to update company (${response.status})`);
      }
      return data;
    },
    onMutate: async ({ companyId, patch }) => {
      const detailKey = queryKeys.companies.detail(companyId);
      await qc.cancelQueries({ queryKey: detailKey });
      await qc.cancelQueries({ queryKey: queryKeys.companies.all() });

      // Drop undefined keys so we never overwrite a value with `undefined`.
      const delta = Object.fromEntries(
        Object.entries(patch).filter(([, v]) => v !== undefined),
      ) as Partial<CompanyDetail>;

      const prevDetail = qc.getQueryData<CompanyDetail>(detailKey);
      if (prevDetail) {
        qc.setQueryData<CompanyDetail>(detailKey, { ...prevDetail, ...delta });
      }

      const prevLists: [readonly unknown[], Company[]][] = [];
      for (const [key, list] of qc.getQueriesData<Company[]>({
        queryKey: queryKeys.companies.all(),
      })) {
        if (!Array.isArray(list)) continue;
        prevLists.push([key, list]);
        qc.setQueryData<Company[]>(
          key,
          list.map((c) => (c.id === companyId ? { ...c, ...delta } : c)),
        );
      }

      return { detailKey, prevDetail, prevLists };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      if (ctx.prevDetail) qc.setQueryData(ctx.detailKey, ctx.prevDetail);
      for (const [key, list] of ctx.prevLists) qc.setQueryData(key, list);
    },
    onSettled: (_data, _err, { companyId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.companies.detail(companyId) });
      qc.invalidateQueries({ queryKey: queryKeys.companies.all() });
    },
  });
}
