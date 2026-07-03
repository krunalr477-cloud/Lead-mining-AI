"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type {
  Campaign,
  CampaignCreate,
  CampaignDetail,
  CampaignTestRequest,
  OutreachQueueFilters,
  OutreachQueueRow,
} from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/** GET /campaigns — bare array. Returns [] on 404/501 so screens degrade. */
export function useCampaigns() {
  return useQuery<Campaign[]>({
    queryKey: queryKeys.campaigns.list(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/campaigns");
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load campaigns (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /campaigns/{id} — detail (with eligibility). null on 404 (not built yet). */
export function useCampaign(campaignId: string | null | undefined) {
  return useQuery<CampaignDetail | null>({
    enabled: !!campaignId,
    queryKey: queryKeys.campaigns.detail(campaignId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/campaigns/{campaign_id}",
        { params: { path: { campaign_id: campaignId! } } },
      );
      if (response.status === 404 || response.status === 501) return null;
      if (!response.ok || !data) {
        throw new Error(`Failed to load campaign (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /campaigns/{id}/queue — per-message outreach rows for one campaign. */
export function useCampaignQueue(
  campaignId: string | null | undefined,
  filters: OutreachQueueFilters = {},
) {
  return useQuery<OutreachQueueRow[]>({
    enabled: !!campaignId,
    queryKey: queryKeys.campaigns.queue(campaignId ?? "", filters),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/campaigns/{campaign_id}/queue",
        {
          params: {
            path: { campaign_id: campaignId! },
            query: cleanParams(filters),
          },
        },
      );
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load campaign queue (${response.status})`);
      }
      return data;
    },
  });
}

/** POST /campaigns — create a draft. Invalidates the list on success. */
export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation<CampaignDetail, Error, CampaignCreate>({
    mutationFn: async (body) => {
      const { data, response } = await api.POST("/api/v1/campaigns", { body });
      if (!response.ok || !data) {
        throw new Error(`Failed to create campaign (${response.status})`);
      }
      return data;
    },
    onSuccess: (campaign) => {
      qc.setQueryData(queryKeys.campaigns.detail(campaign.id), campaign);
      qc.invalidateQueries({ queryKey: queryKeys.campaigns.all() });
    },
  });
}

/** Shared factory for the lifecycle POST actions (launch/pause/resume/cancel). */
function useCampaignAction(action: "launch" | "pause" | "resume" | "cancel") {
  const qc = useQueryClient();
  return useMutation<CampaignDetail, Error, string>({
    mutationFn: async (campaignId) => {
      const { data, response } = await api.POST(
        `/api/v1/campaigns/{campaign_id}/${action}` as "/api/v1/campaigns/{campaign_id}/launch",
        { params: { path: { campaign_id: campaignId } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to ${action} campaign (${response.status})`);
      }
      return data;
    },
    onSuccess: (campaign) => {
      qc.setQueryData(queryKeys.campaigns.detail(campaign.id), campaign);
      qc.invalidateQueries({ queryKey: queryKeys.campaigns.all() });
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.all() });
    },
  });
}

export function useLaunch() {
  return useCampaignAction("launch");
}
export function usePause() {
  return useCampaignAction("pause");
}
export function useResume() {
  return useCampaignAction("resume");
}
export function useCancel() {
  return useCampaignAction("cancel");
}

export interface TestSendVars {
  campaignId: string;
  body?: CampaignTestRequest;
}

/** POST /campaigns/{id}/test — send a single test email. */
export function useTestSend() {
  return useMutation<{ ok: boolean; message?: string }, Error, TestSendVars>({
    mutationFn: async ({ campaignId, body }) => {
      const { data, response } = await api.POST(
        "/api/v1/campaigns/{campaign_id}/test",
        { params: { path: { campaign_id: campaignId } }, body: body ?? {} },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to send test email (${response.status})`);
      }
      return data;
    },
  });
}
