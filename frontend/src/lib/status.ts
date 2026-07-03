/**
 * SINGLE source of truth mapping every backend status string to a visual
 * treatment for <StatusChip>. Any status the backend can emit — job, email
 * validation, campaign, message, bounce — resolves through resolveStatus().
 *
 * Variant -> color token (see globals.css @theme):
 *   accent -> #00F0A8  (positive / verified / delivered / sales-ready)
 *   danger -> #FF4D5E  (invalid / rejected / hard bounce / failed)
 *   review -> #9D7CFF  (needs human review / catch-all / unknown / risk)
 *   info   -> #61D7FF  (in-flight: running / queued / sending)
 *   warn   -> #F8C64E  (soft warnings / soft bounce)
 *   muted  -> #7B8494  (idle: paused / draft / neutral)
 */

export type StatusVariant = "accent" | "danger" | "review" | "info" | "warn" | "muted";

export interface StatusMeta {
  variant: StatusVariant;
  /** Human label (Title Case) for display. */
  label: string;
  /** CSS var() color for the LED dot / text tint. */
  color: string;
}

const VARIANT_COLOR: Record<StatusVariant, string> = {
  accent: "var(--color-accent)",
  danger: "var(--color-danger)",
  review: "var(--color-review)",
  info: "var(--color-info)",
  warn: "var(--color-warn)",
  muted: "var(--color-muted)",
};

/** Raw backend status -> variant. Keys are lowercased & underscore-normalized. */
const STATUS_VARIANT: Record<string, StatusVariant> = {
  // ---- positive / done ----
  verified: "accent",
  valid: "accent",
  delivered: "accent",
  sales_ready: "accent",
  completed: "accent",
  sent: "accent",
  replied: "accent",
  opened: "accent",
  clicked: "accent",
  passed: "accent",
  pass: "accent",
  live: "accent",
  active: "accent",
  connected: "accent",

  // ---- hard failures ----
  invalid: "danger",
  invalid_syntax: "danger",
  rejected: "danger",
  provider_invalid: "danger",
  disposable_rejected: "danger",
  role_based_rejected: "danger",
  mx_failed: "danger",
  hard_bounce: "danger",
  bounced: "danger",
  failed: "danger",
  blocked: "danger",
  spam_complaint: "danger",
  spam_rejected: "danger",
  suppressed: "danger",
  unsubscribed: "danger",
  cancelled: "danger",
  canceled: "danger",
  error: "danger",
  disabled: "danger",

  // ---- needs review ----
  review: "review",
  catch_all: "review",
  catch_all_review: "review",
  unknown: "review",
  unknown_retry: "review",
  risk: "review",
  risk_review: "review",
  llm_low_confidence: "review",
  needs_review: "review",
  gated: "review",

  // ---- in flight ----
  running: "info",
  queued: "info",
  sending: "info",
  scheduled: "info",
  processing: "info",
  syncing: "info",
  pending: "info",
  retry: "info",
  retrying: "info",

  // ---- soft warnings ----
  warning: "warn",
  soft_bounce: "warn",
  rate_limited: "warn",
  mailbox_full: "warn",
  degraded: "warn",
  mock: "warn",

  // ---- idle / neutral ----
  paused: "muted",
  draft: "muted",
  idle: "muted",
  not_started: "muted",
  archived: "muted",
};

function normalizeKey(status: string): string {
  return status.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function humanize(status: string): string {
  return status
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Resolve any backend status string to a StatusMeta. Unknown values fall back
 * to the `muted` variant with a humanized label rather than throwing, so a new
 * backend status never crashes the UI.
 */
export function resolveStatus(status: string | null | undefined): StatusMeta {
  const raw = status ?? "";
  const key = normalizeKey(raw);
  const variant = STATUS_VARIANT[key] ?? "muted";
  return {
    variant,
    label: raw ? humanize(raw) : "—",
    color: VARIANT_COLOR[variant],
  };
}

export function statusColor(variant: StatusVariant): string {
  return VARIANT_COLOR[variant];
}
