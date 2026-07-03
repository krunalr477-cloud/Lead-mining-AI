"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { MeResponse } from "../schema";

/**
 * Fetch the current session envelope (user, tenant, demo_mode, providers).
 * Returns null (not an error) on 401 so callers can treat "not logged in" as a
 * normal state without try/catch.
 */
export function useMe() {
  return useQuery<MeResponse | null>({
    queryKey: queryKeys.me(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/me");
      if (response.status === 401) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load session (${response.status})`);
      }
      return data;
    },
    staleTime: 30_000,
    retry: false,
  });
}
