"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type { Template, TemplateCreate } from "../schema";

/** GET /templates — reusable subject/body templates. [] on 404. */
export function useTemplates() {
  return useQuery<Template[]>({
    queryKey: queryKeys.templates.list(),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/templates");
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load templates (${response.status})`);
      }
      return data;
    },
  });
}

/** POST /templates — create a template. */
export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation<Template, Error, TemplateCreate>({
    mutationFn: async (body) => {
      const { data, response } = await api.POST("/api/v1/templates", { body });
      if (!response.ok || !data) {
        throw new Error(`Failed to create template (${response.status})`);
      }
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.templates.all() });
    },
  });
}
