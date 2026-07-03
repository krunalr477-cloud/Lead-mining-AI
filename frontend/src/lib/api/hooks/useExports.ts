"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { ExportCreate, ExportRecord } from "../schema";
import { apiFetch } from "./http";

/** GET /exports — history of generated exports. []-on-404 for EmptyState. */
export function useExports() {
  return useQuery<ExportRecord[]>({
    queryKey: queryKeys.exports.list(),
    // Poll while any export is still processing so status chips + download
    // links update without a manual refresh.
    refetchInterval: (query) => {
      const rows = query.state.data as ExportRecord[] | undefined;
      const pending = rows?.some((r) =>
        ["pending", "queued", "running", "processing"].includes(
          String(r.status).toLowerCase(),
        ),
      );
      return pending ? 4_000 : false;
    },
    queryFn: () =>
      apiFetch<ExportRecord[], ExportRecord[]>("/exports", {
        notFoundValue: [],
        label: "Load exports",
      }),
  });
}

/** GET /exports/{id} — single export (download URL once completed). */
export function useExport(exportId: string | null | undefined) {
  return useQuery<ExportRecord | null>({
    enabled: !!exportId,
    queryKey: queryKeys.exports.detail(exportId ?? ""),
    queryFn: () =>
      apiFetch<ExportRecord, null>(`/exports/${exportId}`, {
        notFoundValue: null,
        label: "Load export",
      }),
  });
}

/** POST /exports — kick off a new export. Invalidates the history list. */
export function useCreateExport() {
  const qc = useQueryClient();
  return useMutation<ExportRecord, Error, ExportCreate>({
    mutationFn: (body) =>
      apiFetch<ExportRecord>("/exports", {
        method: "POST",
        body,
        label: "Create export",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.exports.list() });
    },
  });
}
