"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { DataSource, SourcePatch } from "../schema";
import { apiFetch } from "./http";

/** GET /sources — data-source compliance rows. []-on-404. */
export function useSources() {
  return useQuery<DataSource[]>({
    queryKey: queryKeys.settings.sources(),
    queryFn: () =>
      apiFetch<DataSource[], DataSource[]>("/sources", {
        notFoundValue: [],
        label: "Load sources",
      }),
  });
}

export interface PatchSourceVars {
  name: string;
  patch: SourcePatch;
}

/** PATCH /sources/{name} — toggle enabled state. */
export function usePatchSource() {
  const qc = useQueryClient();
  return useMutation<DataSource, Error, PatchSourceVars>({
    mutationFn: ({ name, patch }) =>
      apiFetch<DataSource>(`/sources/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: patch,
        label: "Update source",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.sources() });
    },
  });
}

/** POST /sources/{name}/signoff — admin/legal sign-off for a gated source. */
export function useSignoffSource() {
  const qc = useQueryClient();
  return useMutation<DataSource, Error, string>({
    mutationFn: (name) =>
      apiFetch<DataSource>(`/sources/${encodeURIComponent(name)}/signoff`, {
        method: "POST",
        label: "Sign off source",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.sources() });
    },
  });
}
