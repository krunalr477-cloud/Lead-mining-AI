"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type {
  Integration,
  IntegrationSecretInput,
  IntegrationTestResult,
} from "../schema";
import { apiFetch } from "./http";

/**
 * GET /integrations — provider connection rows. The backend only ever returns
 * a masked_key (e.g. "****ab12"); full secrets are stored server-side and are
 * never sent to the client. []-on-404 so the screen degrades to the /me
 * provider map alone.
 */
export function useIntegrations() {
  return useQuery<Integration[]>({
    queryKey: queryKeys.settings.integrations(),
    queryFn: () =>
      apiFetch<Integration[], Integration[]>("/integrations", {
        notFoundValue: [],
        label: "Load integrations",
      }),
  });
}

/** POST /integrations/{provider}/test — probe a provider connection. */
export function useTestIntegration() {
  const qc = useQueryClient();
  return useMutation<IntegrationTestResult, Error, string>({
    mutationFn: (provider) =>
      apiFetch<IntegrationTestResult>(
        `/integrations/${encodeURIComponent(provider)}/test`,
        { method: "POST", label: "Test integration" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.integrations() });
    },
  });
}

/**
 * PUT /integrations/{provider} — store a provider secret server-side. The
 * request body is the per-provider secret shape ({api_key}, or
 * {client_id, client_secret} for google_oauth, or {base_url, api_key} for
 * approved_providers). Never sends or receives a full key back — the refetched
 * list only carries a masked suffix.
 */
export function useSaveIntegration() {
  const qc = useQueryClient();
  return useMutation<
    Integration,
    Error,
    { provider: string; body: IntegrationSecretInput }
  >({
    mutationFn: ({ provider, body }) =>
      apiFetch<Integration>(`/integrations/${encodeURIComponent(provider)}`, {
        method: "PUT",
        body,
        label: "Save integration",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.integrations() });
    },
  });
}

/** DELETE /integrations/{provider} — remove a stored provider secret. */
export function useDeleteIntegration() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (provider) =>
      apiFetch<void>(`/integrations/${encodeURIComponent(provider)}`, {
        method: "DELETE",
        label: "Remove integration",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.integrations() });
    },
  });
}
