"use client";

import { useMe } from "../api/hooks/useMe";
import type { User, UserRole } from "../api/schema";

/**
 * RBAC action catalog. Keep coarse for the foundation; refine as screens land.
 */
export type Action =
  | "job.create"
  | "job.run"
  | "campaign.create"
  | "campaign.launch"
  | "sheets.sync"
  | "export.create"
  | "settings.manage"
  | "users.manage"
  | "audit.view"
  | "lead.disposition";

/** Role -> allowed actions. Admin is implicitly allowed everything via can(). */
const ROLE_ACTIONS: Record<UserRole, Action[]> = {
  admin: [
    "job.create",
    "job.run",
    "campaign.create",
    "campaign.launch",
    "sheets.sync",
    "export.create",
    "settings.manage",
    "users.manage",
    "audit.view",
    "lead.disposition",
  ],
  sales_manager: [
    "job.create",
    "job.run",
    "campaign.create",
    "campaign.launch",
    "sheets.sync",
    "export.create",
    "audit.view",
    "lead.disposition",
  ],
  sales_executive: ["campaign.create", "lead.disposition", "export.create"],
  viewer: [],
};

/** Pure permission check — usable outside React. */
export function can(role: UserRole | null | undefined, action: Action): boolean {
  if (!role) return false;
  if (role === "admin") return true;
  return ROLE_ACTIONS[role]?.includes(action) ?? false;
}

export interface SessionState {
  user: User | null;
  tenant: { id: string; name: string } | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  can: (action: Action) => boolean;
}

/**
 * Primary session hook. Thin wrapper over useMe() exposing the pieces screens
 * actually need plus a bound `can()`.
 */
export function useSession(): SessionState {
  const { data, isLoading } = useMe();
  const role = data?.user.role ?? null;

  return {
    user: data?.user ?? null,
    tenant: data?.tenant ?? null,
    role,
    isAuthenticated: Boolean(data?.user),
    isLoading,
    can: (action: Action) => can(role, action),
  };
}
