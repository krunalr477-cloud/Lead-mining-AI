"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../keys";
import type {
  Contact,
  ContactBrief,
  ContactDetail,
  ContactPatch,
  ContactsFilters,
  ValidationRow,
} from "../schema";

function cleanParams<T extends Record<string, unknown>>(filters: T) {
  const query: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") query[k] = v;
  }
  return query;
}

/** GET /contacts — bare array. */
export function useContacts(filters: ContactsFilters = {}) {
  return useQuery<Contact[]>({
    queryKey: queryKeys.contacts.list(filters),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/contacts", {
        params: { query: cleanParams(filters) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok || !data) {
        throw new Error(`Failed to load contacts (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /contacts/{id} — detail with validation_checks. */
export function useContact(contactId: string | null | undefined) {
  return useQuery<ContactDetail>({
    enabled: !!contactId,
    queryKey: queryKeys.contacts.detail(contactId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/contacts/{contact_id}",
        { params: { path: { contact_id: contactId! } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to load contact (${response.status})`);
      }
      return data;
    },
  });
}

/** GET /validation/{contact_id}/history — full validation history for a contact. */
export function useContactHistory(contactId: string | null | undefined) {
  return useQuery<ValidationRow[]>({
    enabled: !!contactId,
    queryKey: queryKeys.contacts.history(contactId ?? ""),
    queryFn: async () => {
      const { data, response } = await api.GET(
        "/api/v1/validation/{contact_id}/history",
        { params: { path: { contact_id: contactId! } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to load contact history (${response.status})`);
      }
      return data;
    },
  });
}

export interface PatchContactVars {
  contactId: string;
  patch: ContactPatch;
}

/**
 * PATCH /contacts/{id} (owner/notes/next_action; sales_ready/primary_contact).
 * Optimistically updates the contact detail cache, any contact list caches, and
 * the ContactBrief entries embedded in company detail caches. Rolls back on
 * error, invalidates on settle.
 */
export function usePatchContact() {
  const qc = useQueryClient();
  return useMutation<
    Contact,
    Error,
    PatchContactVars,
    {
      detailKey: readonly unknown[];
      prevDetail?: ContactDetail;
      prevLists: [readonly unknown[], Contact[]][];
      prevCompanies: [readonly unknown[], { contacts?: ContactBrief[] }][];
    }
  >({
    mutationFn: async ({ contactId, patch }) => {
      const { data, response } = await api.PATCH(
        "/api/v1/contacts/{contact_id}",
        { params: { path: { contact_id: contactId } }, body: patch },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to update contact (${response.status})`);
      }
      return data;
    },
    onMutate: async ({ contactId, patch }) => {
      const detailKey = queryKeys.contacts.detail(contactId);
      await qc.cancelQueries({ queryKey: detailKey });
      await qc.cancelQueries({ queryKey: queryKeys.contacts.all() });
      await qc.cancelQueries({ queryKey: queryKeys.companies.all() });

      const delta = Object.fromEntries(
        Object.entries(patch).filter(([, v]) => v !== undefined),
      ) as Partial<ContactDetail>;

      const prevDetail = qc.getQueryData<ContactDetail>(detailKey);
      if (prevDetail) {
        qc.setQueryData<ContactDetail>(detailKey, { ...prevDetail, ...delta });
      }

      const prevLists: [readonly unknown[], Contact[]][] = [];
      for (const [key, list] of qc.getQueriesData<Contact[]>({
        queryKey: queryKeys.contacts.all(),
      })) {
        if (!Array.isArray(list)) continue;
        prevLists.push([key, list]);
        qc.setQueryData<Contact[]>(
          key,
          list.map((c) => (c.id === contactId ? { ...c, ...delta } : c)),
        );
      }

      // ContactBrief supports a subset of patch fields; apply what overlaps.
      const briefPatch: Partial<ContactBrief> = {};
      if ("primary_contact" in patch)
        briefPatch.primary_contact = patch.primary_contact!;
      if ("sales_ready" in patch) briefPatch.sales_ready = patch.sales_ready!;

      const prevCompanies: [readonly unknown[], { contacts?: ContactBrief[] }][] = [];
      if (Object.keys(briefPatch).length > 0) {
        for (const [key, comp] of qc.getQueriesData<{ contacts?: ContactBrief[] }>({
          queryKey: queryKeys.companies.all(),
        })) {
          if (!comp || !Array.isArray(comp.contacts)) continue;
          prevCompanies.push([key, comp]);
          qc.setQueryData(key, {
            ...comp,
            contacts: comp.contacts.map((c) =>
              c.id === contactId ? { ...c, ...briefPatch } : c,
            ),
          });
        }
      }

      return { detailKey, prevDetail, prevLists, prevCompanies };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      if (ctx.prevDetail) qc.setQueryData(ctx.detailKey, ctx.prevDetail);
      for (const [key, list] of ctx.prevLists) qc.setQueryData(key, list);
      for (const [key, comp] of ctx.prevCompanies) qc.setQueryData(key, comp);
    },
    onSettled: (_data, _err, { contactId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.contacts.detail(contactId) });
      qc.invalidateQueries({ queryKey: queryKeys.contacts.all() });
      qc.invalidateQueries({ queryKey: queryKeys.companies.all() });
    },
  });
}

/**
 * POST /contacts/{id}/verify — re-run verification for a single contact. On
 * success patches the returned contact into caches and invalidates its
 * validation history + detail.
 */
export function useRevalidateContact() {
  const qc = useQueryClient();
  return useMutation<Contact, Error, string>({
    mutationFn: async (contactId) => {
      const { data, response } = await api.POST(
        "/api/v1/contacts/{contact_id}/verify",
        { params: { path: { contact_id: contactId } } },
      );
      if (!response.ok || !data) {
        throw new Error(`Failed to verify contact (${response.status})`);
      }
      return data;
    },
    onSuccess: (contact) => {
      qc.setQueryData<ContactDetail | undefined>(
        queryKeys.contacts.detail(contact.id),
        (prev) => (prev ? { ...prev, ...contact } : prev),
      );
      qc.invalidateQueries({ queryKey: queryKeys.contacts.detail(contact.id) });
      qc.invalidateQueries({ queryKey: queryKeys.contacts.history(contact.id) });
      qc.invalidateQueries({ queryKey: queryKeys.contacts.all() });
    },
  });
}
