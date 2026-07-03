"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { SheetsEvent, SheetsStatus } from "../schema";
import { apiFetch } from "./http";

/**
 * GET /sheets/status — Google Sheets sync connection + per-tab row counts,
 * last sync time, pending/failed rows. Polls on an interval so the dashboard
 * card reflects live sync progress. Resolves to null on 404/501 so the card
 * degrades to a "not connected / unavailable" state rather than crashing.
 */
export function useSheetsStatus(refetchIntervalMs = 15_000) {
  return useQuery<SheetsStatus | null>({
    queryKey: queryKeys.sheets.status(),
    refetchInterval: refetchIntervalMs,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/sheets/status");
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load sheets status (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /sheets/events — recent sync events / failed-row log. []-on-404. */
export function useSheetsEvents() {
  return useQuery<SheetsEvent[]>({
    queryKey: queryKeys.sheets.events(),
    queryFn: () =>
      apiFetch<SheetsEvent[], SheetsEvent[]>("/sheets/events", {
        notFoundValue: [],
        label: "Load sheets events",
      }),
  });
}

/** POST /sheets/sync — push pending rows to the spreadsheet now. */
export function useSyncSheets() {
  const qc = useQueryClient();
  return useMutation<SheetsStatus | null, Error, void>({
    mutationFn: () =>
      apiFetch<SheetsStatus, null>("/sheets/sync", {
        method: "POST",
        notFoundValue: null,
        label: "Sync sheets",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sheets.status() });
      qc.invalidateQueries({ queryKey: queryKeys.sheets.events() });
    },
  });
}

/** POST /sheets/connect — connect / re-provision the tenant spreadsheet. */
export function useConnectSheets() {
  const qc = useQueryClient();
  return useMutation<SheetsStatus | null, Error, void>({
    mutationFn: () =>
      apiFetch<SheetsStatus, null>("/sheets/connect", {
        method: "POST",
        notFoundValue: null,
        label: "Connect sheets",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sheets.status() });
    },
  });
}
