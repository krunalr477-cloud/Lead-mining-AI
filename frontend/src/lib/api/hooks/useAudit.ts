"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { AuditEntry, AuditFilters } from "../schema";
import { apiFetch } from "./http";

/** GET /audit — mutation ledger (actor / action / entity / before-after). */
export function useAudit(filters: AuditFilters = {}) {
  return useQuery<AuditEntry[]>({
    queryKey: queryKeys.settings.audit(filters),
    queryFn: () =>
      apiFetch<AuditEntry[], AuditEntry[]>("/audit", {
        notFoundValue: [],
        query: filters,
        label: "Load audit log",
      }),
  });
}
