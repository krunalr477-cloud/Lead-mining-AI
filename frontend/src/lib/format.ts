import { format, formatDistanceToNowStrict, parseISO, isValid } from "date-fns";

function toDate(value: Date | string | number | null | undefined): Date | null {
  if (value == null) return null;
  if (value instanceof Date) return isValid(value) ? value : null;
  if (typeof value === "number") {
    const d = new Date(value);
    return isValid(d) ? d : null;
  }
  const d = parseISO(value);
  return isValid(d) ? d : null;
}

/** "Jul 3, 2026" */
export function formatDate(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "MMM d, yyyy") : "—";
}

/** "Jul 3, 2026, 14:08" (24h) */
export function formatDateTime(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "MMM d, yyyy, HH:mm") : "—";
}

/** "3m ago", "2h ago" */
export function formatRelative(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  return d ? `${formatDistanceToNowStrict(d)} ago` : "—";
}

const numberFmt = new Intl.NumberFormat("en-US");
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** 12,480 */
export function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? numberFmt.format(value) : "—";
}

/** 12.4K, 1.2M — for dense metric captions. */
export function formatCompact(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? compactFmt.format(value) : "—";
}

/** 3.1% from a ratio (0.031) or percent (3.1) — pass `fromRatio` to choose. */
export function formatPercent(
  value: number | null | undefined,
  { fromRatio = false, digits = 1 }: { fromRatio?: boolean; digits?: number } = {},
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const pct = fromRatio ? value * 100 : value;
  return `${pct.toFixed(digits)}%`;
}

/** $128.40 — estimated API cost. */
export function formatCurrency(value: number | null | undefined, currency = "USD"): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
}

/** "1,204 km" */
export function formatDistanceKm(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${numberFmt.format(value)} km`
    : "—";
}

/** Right-pad a numeric string for aligned tabular columns (used with font-mono). */
export function tabular(value: number | null | undefined, width = 0): string {
  const s = formatNumber(value);
  return width > 0 ? s.padStart(width, " ") : s;
}

/** ms/seconds duration -> "2m 14s". Accepts milliseconds. */
export function formatDuration(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.round(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** Truncate long strings with an ellipsis, whitespace-safe. */
export function truncate(value: string | null | undefined, max = 48): string {
  if (!value) return "—";
  return value.length > max ? `${value.slice(0, max - 1).trimEnd()}…` : value;
}
