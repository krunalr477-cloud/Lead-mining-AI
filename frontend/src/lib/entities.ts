/**
 * Shared mappers for entity/results/validation UI. Keeps the backend's raw
 * source names + compliance strings translated into the design-system posture
 * badges and human labels in ONE place so the drawers, results table, and
 * validation table stay consistent.
 */

import type { CompliancePosture } from "@/components/ui/ComplianceBadge";

/** Human labels for the raw source_name / selected_sources slugs. */
const SOURCE_LABELS: Record<string, string> = {
  google_maps: "Google Maps",
  company_websites: "Websites",
  directories: "Directories",
  facebook_signals: "Facebook",
  facebook: "Facebook",
  serp: "Web Search",
  rocketreach: "RocketReach",
  linkedin: "LinkedIn",
  crawler: "Crawler",
  hiring_boards: "Hiring Boards",
};

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "—";
  return (
    SOURCE_LABELS[source.toLowerCase()] ??
    source
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/**
 * Map a backend compliance_posture / access_method string onto the three
 * ComplianceBadge postures. The backend uses a traffic-light vocabulary
 * ("green"/"amber"/"red") for companies and "official"/"gated"/"disabled" plus
 * access_method ("official_api"/"licensed"/"scrape"/"mock") for sources.
 */
export function toCompliancePosture(
  posture: string | null | undefined,
  accessMethod?: string | null,
): CompliancePosture {
  const p = (posture ?? "").toLowerCase();
  const a = (accessMethod ?? "").toLowerCase();

  if (
    ["red", "disabled", "blocked", "prohibited"].includes(p) ||
    ["scrape", "scraping", "disabled"].includes(a)
  ) {
    return "disabled";
  }
  if (
    ["amber", "yellow", "gated", "review", "restricted"].includes(p) ||
    ["gated", "licensed"].includes(a)
  ) {
    return "gated";
  }
  // green / official / official_api / mock all read as cleared-for-use.
  return "official";
}

/** Parse a decimal-as-string field to a number, or null. */
export function num(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** A rating like "3.90" -> "3.9". */
export function formatRating(value: string | number | null | undefined): string {
  const n = num(value);
  return n == null ? "—" : n.toFixed(1);
}

/** Confidence "0.744" -> "74%". */
export function formatConfidencePct(
  value: string | number | null | undefined,
): string {
  const n = num(value);
  return n == null ? "—" : `${Math.round(n * 100)}%`;
}
