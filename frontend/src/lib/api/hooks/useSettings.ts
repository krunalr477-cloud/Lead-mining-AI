"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { Settings } from "../schema";
import { apiFetch } from "./http";

/** GET /settings — tenant settings blob. null-on-404. */
export function useSettings() {
  return useQuery<Settings | null>({
    queryKey: queryKeys.settings.all(),
    queryFn: () =>
      apiFetch<Settings, null>("/settings", {
        notFoundValue: null,
        label: "Load settings",
      }),
  });
}

/** PATCH /settings — partial update of the settings blob. */
export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, Partial<Settings>>({
    mutationFn: (body) =>
      apiFetch<Settings>("/settings", {
        method: "PATCH",
        body,
        label: "Update settings",
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.settings.all(), data);
    },
  });
}
