"use client";

import type { ReactNode } from "react";
import { useSession, type Action } from "./session";

interface RoleGateProps {
  /** Action(s) required — user must satisfy at least one. */
  action: Action | Action[];
  children: ReactNode;
  /** Rendered when the user lacks permission. Defaults to nothing. */
  fallback?: ReactNode;
}

/**
 * Conditionally render children based on the current user's RBAC permissions.
 * While the session is loading, renders nothing to avoid a permission flash.
 */
export function RoleGate({ action, children, fallback = null }: RoleGateProps) {
  const { can, isLoading } = useSession();
  if (isLoading) return null;
  const actions = Array.isArray(action) ? action : [action];
  const allowed = actions.some((a) => can(a));
  return <>{allowed ? children : fallback}</>;
}
