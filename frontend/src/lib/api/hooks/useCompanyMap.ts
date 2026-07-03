"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import type { Company } from "../schema";

const PAGE = 200; // backend hard cap on limit
const MAX_PAGES = 25; // safety valve — 5,000 companies

/**
 * Fetch ALL companies for a job (looping offset pages of 200, the backend cap)
 * and index them by id. Used by the Mining Results table to join company
 * identity (name/city/rating/domain) onto the paged contacts feed, since the
 * contacts endpoint only returns company_id. Cached for 60s.
 */
export function useCompanyMap(jobId: string | null | undefined) {
  return useQuery<Record<string, Company>>({
    enabled: !!jobId,
    queryKey: ["companies", "map", jobId ?? ""],
    staleTime: 60_000,
    queryFn: async () => {
      const map: Record<string, Company> = {};
      for (let page = 0; page < MAX_PAGES; page++) {
        const { data, response } = await api.GET("/api/v1/companies", {
          params: {
            query: { job_id: jobId!, limit: PAGE, offset: page * PAGE },
          },
        });
        if (!response.ok || !data) {
          if (page === 0) throw new Error(`Failed to load companies (${response.status})`);
          break;
        }
        for (const c of data) map[c.id] = c;
        if (data.length < PAGE) break;
      }
      return map;
    },
  });
}
