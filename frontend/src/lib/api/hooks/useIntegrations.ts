"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { Integration, IntegrationTestResult } from "../schema";
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
