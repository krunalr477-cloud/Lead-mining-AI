import { API_BASE } from "../client";

/**
 * Minimal same-origin JSON fetch for endpoints not modelled in the openapi
 * `paths` map (Sheets sync, Exports, Settings, Sources, Integrations,
 * Validation rules, Users, Audit). Several of these are still being built by a
 * parallel backend workflow and may 404 — callers pass `notFoundValue` so a
 * missing route degrades to an EmptyState instead of throwing.
 *
 * Cookies ride along (`credentials: "include"`) exactly like the typed client.
 */

interface RequestOpts<TNotFound> {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Value to resolve to on a 404/501 instead of throwing. */
  notFoundValue?: TNotFound;
  /** Extra query params. */
  query?: Record<string, unknown>;
  label?: string;
}

function buildQuery(query?: Record<string, unknown>): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function apiFetch<TData, TNotFound = never>(
  path: string,
  opts: RequestOpts<TNotFound> = {},
): Promise<TData | TNotFound> {
  const { method = "GET", body, notFoundValue, query, label } = opts;
  const res = await fetch(`${API_BASE}${path}${buildQuery(query)}`, {
    method,
    credentials: "include",
    headers: body != null ? { "Content-Type": "application/json" } : undefined,
    body: body != null ? JSON.stringify(body) : undefined,
  });

  if (
    (res.status === 404 || res.status === 501) &&
    notFoundValue !== undefined
  ) {
    return notFoundValue;
  }

  if (!res.ok) {
    let detail = "";
    try {
      const j = (await res.json()) as { detail?: string };
      detail = j?.detail ? ` — ${j.detail}` : "";
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${label ?? "Request"} failed (${res.status})${detail}`);
  }

  if (res.status === 204) return undefined as TData;
  return (await res.json()) as TData;
}
