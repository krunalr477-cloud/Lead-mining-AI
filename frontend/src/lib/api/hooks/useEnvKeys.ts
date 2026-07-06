"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { EnvKey, EnvKeyReveal } from "../schema";
import { apiFetch } from "./http";

/**
 * GET /settings/env-keys — the `.env` key rows the admin can view and edit.
 * Secret rows carry only a masked hint; the full value is fetched on demand via
 * useRevealEnvKey. []-on-404 so the section degrades gracefully while the
 * backend route is still landing.
 */
export function useEnvKeys() {
  return useQuery<EnvKey[]>({
    queryKey: queryKeys.settings.envKeys(),
    queryFn: () =>
      apiFetch<EnvKey[], EnvKey[]>("/settings/env-keys", {
        notFoundValue: [],
        label: "Load environment keys",
      }),
  });
}

/**
 * POST /settings/env-keys/reveal — return the full plaintext for a single
 * secret key. Admin-only server-side; the value is held in component state only
 * briefly and never cached in the query client.
 */
export function useRevealEnvKey() {
  return useMutation<EnvKeyReveal, Error, string>({
    mutationFn: (key) =>
      apiFetch<EnvKeyReveal>("/settings/env-keys/reveal", {
        method: "POST",
        body: { key },
        label: "Reveal environment key",
      }),
  });
}

/**
 * PUT /settings/env-keys — write one or more `.env` values. The backend writes
 * to the repo `.env`, hot-reloads settings, and returns the refreshed key list,
 * which we push straight into the cache.
 */
export function useUpdateEnvKeys() {
  const qc = useQueryClient();
  return useMutation<EnvKey[], Error, Record<string, string>>({
    mutationFn: (values) =>
      apiFetch<EnvKey[]>("/settings/env-keys", {
        method: "PUT",
        body: { values },
        label: "Update environment keys",
      }),
    onSuccess: (data) => {
      if (Array.isArray(data)) {
        qc.setQueryData(queryKeys.settings.envKeys(), data);
      }
      qc.invalidateQueries({ queryKey: queryKeys.settings.envKeys() });
      // Provider modes derive from env — refetch integrations too.
      qc.invalidateQueries({ queryKey: queryKeys.settings.integrations() });
    },
  });
}
