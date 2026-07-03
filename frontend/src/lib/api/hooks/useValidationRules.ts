"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { ValidationRules, ValidationRulesPatch } from "../schema";
import { apiFetch } from "./http";

/** GET /validation-rules — the knobs gating Sales_Ready_Leads. null-on-404. */
export function useValidationRules() {
  return useQuery<ValidationRules | null>({
    queryKey: queryKeys.settings.validationRules(),
    queryFn: () =>
      apiFetch<ValidationRules, null>("/validation-rules", {
        notFoundValue: null,
        label: "Load validation rules",
      }),
  });
}

/** PATCH /validation-rules — partial update. */
export function usePatchValidationRules() {
  const qc = useQueryClient();
  return useMutation<ValidationRules, Error, ValidationRulesPatch>({
    mutationFn: (body) =>
      apiFetch<ValidationRules>("/validation-rules", {
        method: "PATCH",
        body,
        label: "Update validation rules",
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.settings.validationRules(), data);
    },
  });
}
