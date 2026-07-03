"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../keys";
import type { User, UserInvite, UserPatch } from "../schema";
import { apiFetch } from "./http";

/** GET /users — tenant members. []-on-404. */
export function useUsers() {
  return useQuery<User[]>({
    queryKey: queryKeys.settings.users(),
    queryFn: () =>
      apiFetch<User[], User[]>("/users", {
        notFoundValue: [],
        label: "Load users",
      }),
  });
}

/** POST /users/invite — invite a new member with a role. */
export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation<User, Error, UserInvite>({
    mutationFn: (body) =>
      apiFetch<User>("/users/invite", {
        method: "POST",
        body,
        label: "Invite user",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.users() });
    },
  });
}

export interface PatchUserVars {
  id: string;
  patch: UserPatch;
}

/** PATCH /users/{id} — change role / name. */
export function usePatchUser() {
  const qc = useQueryClient();
  return useMutation<User, Error, PatchUserVars>({
    mutationFn: ({ id, patch }) =>
      apiFetch<User>(`/users/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: patch,
        label: "Update user",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.users() });
    },
  });
}
