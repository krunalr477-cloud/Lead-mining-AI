"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import type { Contact } from "../schema";

const PAGE = 200; // backend hard cap on limit
const MAX_PAGES = 25;

/**
 * Fetch ALL contacts for a job (looping offset pages of 200) and index them by
 * id. Used by the Validation Pipeline to join contact identity (name/email/
 * company) onto validation rows, which only carry contact_id. Cached 60s.
 */
export function useContactMap(jobId: string | null | undefined) {
  return useQuery<Record<string, Contact>>({
    enabled: !!jobId,
    queryKey: ["contacts", "map", jobId ?? ""],
    staleTime: 60_000,
    queryFn: async () => {
      const map: Record<string, Contact> = {};
      for (let page = 0; page < MAX_PAGES; page++) {
        const { data, response } = await api.GET("/api/v1/contacts", {
          params: {
            query: { job_id: jobId!, limit: PAGE, offset: page * PAGE },
          },
        });
        if (!response.ok || !data) {
          if (page === 0) throw new Error(`Failed to load contacts (${response.status})`);
          break;
        }
        for (const c of data) map[c.id] = c;
        if (data.length < PAGE) break;
      }
      return map;
    },
  });
}
