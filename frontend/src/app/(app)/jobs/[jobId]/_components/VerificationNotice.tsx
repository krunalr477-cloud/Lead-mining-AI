"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import type { JobTotals } from "@/lib/api/schema";

/**
 * Shown when a finished run found emails but verified NONE and left them in
 * review — the signature of MillionVerifier being out of credits (every check
 * returns "unknown" → UNKNOWN_RETRY). The beat retries them every 6 hours, so
 * topping up credits is all that's needed.
 */
export function VerificationNotice({
  totals,
  active,
}: {
  totals: JobTotals | undefined;
  active: boolean;
}) {
  const review = totals?.review_emails ?? 0;
  const verified = totals?.verified_emails ?? 0;
  const found = totals?.emails_found ?? 0;
  if (active || review <= 0 || verified !== 0 || found <= 0) return null;

  return (
    <div
      className="flex items-start gap-2.5 rounded-[8px] border px-3 py-2.5 text-sm"
      style={{
        color: "var(--color-review)",
        borderColor: "color-mix(in srgb, var(--color-review) 30%, transparent)",
        backgroundColor: "color-mix(in srgb, var(--color-review) 8%, transparent)",
      }}
      role="status"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="text-ink/90">
        <span className="font-medium">
          {review} email{review === 1 ? "" : "s"} awaiting external verification
        </span>{" "}
        — check MillionVerifier credits in{" "}
        <Link
          href="/settings/integrations"
          className="underline decoration-dotted underline-offset-2 hover:text-ink"
        >
          Settings → Integrations
        </Link>
        . They retry automatically every 6 hours.
      </p>
    </div>
  );
}
