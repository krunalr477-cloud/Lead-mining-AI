"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { Suppression, SuppressionCreate } from "../schema";

/** GET /suppressions — suppressed email addresses. [] on 404/501. */
export function useSuppressions() {
  const list = useQuery<Suppression[]>({
    queryKey: queryKeys.suppressions.list(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/suppressions");
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load suppressions (${response.status})`);
      }
      return data;
    },
  });

  const qc = useQueryClient();

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: queryKeys.suppressions.all() });
    qc.invalidateQueries({ queryKey: queryKeys.bounces.all() });
    qc.invalidateQueries({ queryKey: queryKeys.contacts.all() });
  };

  /** POST /suppressions — suppress an email. */
  const suppress = useMutation<Suppression, Error, SuppressionCreate>({
    mutationFn: async (body) => {
      const { data, response } = await api.POST("/api/v1/suppressions", { body });
      if (!response.ok || !data) {
        throw new Error(`Failed to suppress email (${response.status})`);
      }
      return data;
    },
    onSuccess: invalidate,
  });

  /** DELETE /suppressions/{id} — un-suppress. */
  const unsuppress = useMutation<void, Error, string>({
    mutationFn: async (suppressionId) => {
      const { response } = await api.DELETE(
        "/api/v1/suppressions/{suppression_id}",
        { params: { path: { suppression_id: suppressionId } } },
      );
      if (!response.ok) {
        throw new Error(`Failed to unsuppress email (${response.status})`);
      }
    },
    onSuccess: invalidate,
  });

  return {
    ...list,
    suppressions: list.data ?? [],
    suppress,
    unsuppress,
  };
}
