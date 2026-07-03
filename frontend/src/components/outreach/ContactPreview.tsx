"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Sparkles } from "lucide-react";
import { Button, MicroLabel, StatusChip } from "@/components/ui";
import { compileTemplate, type PreviewContext } from "./template";
import { UnsubscribeFooter } from "./UnsubscribeFooter";

interface ContactPreviewProps {
  subject: string;
  body: string;
  aiOpener: boolean;
  contexts: PreviewContext[];
  index: number;
  onIndex: (i: number) => void;
}

/**
 * Compiles the subject/body template against a real eligible contact and
 * renders the resulting email with a prev/next stepper. Surfaces any
 * missing-variable or unknown-token warnings for the current contact.
 */
export function ContactPreview({
  subject,
  body,
  aiOpener,
  contexts,
  index,
  onIndex,
}: ContactPreviewProps) {
  const total = contexts.length;

  if (total === 0) {
    return (
      <div className="rounded-[8px] border border-border bg-[var(--color-surface-1)] px-4 py-8 text-center">
        <p className="text-sm text-muted">
          No eligible contact available to preview against.
        </p>
      </div>
    );
  }

  const ctx = contexts[Math.min(index, total - 1)];
  const subj = compileTemplate(subject, ctx);
  const bodyOut = compileTemplate(body, ctx);
  const missing = [...new Set([...subj.missing, ...bodyOut.missing])];
  const unknown = [...new Set([...subj.unknown, ...bodyOut.unknown])];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <MicroLabel>Preview contact</MicroLabel>
          <span className="truncate text-sm font-medium text-ink">
            {ctx.contact.full_name ?? ctx.contact.email ?? "—"}
          </span>
          <span className="truncate font-mono text-[11px] text-muted">
            {ctx.contact.email ?? "—"}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Previous contact"
            disabled={index <= 0}
            onClick={() => onIndex(Math.max(0, index - 1))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="w-12 text-center font-mono text-[11px] tabular-nums text-muted">
            {Math.min(index + 1, total)}/{total}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Next contact"
            disabled={index >= total - 1}
            onClick={() => onIndex(Math.min(total - 1, index + 1))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>

      {(missing.length > 0 || unknown.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 rounded-[8px] border border-warn/30 bg-warn/5 px-3 py-2">
          <AlertTriangle className="size-4 shrink-0 text-warn" />
          {missing.length > 0 && (
            <span className="text-xs text-muted">
              Missing for this contact:{" "}
              <span className="font-mono text-warn">{missing.join(", ")}</span>
            </span>
          )}
          {unknown.length > 0 && (
            <span className="text-xs text-muted">
              Unknown token:{" "}
              <span className="font-mono text-danger">{unknown.join(", ")}</span>
            </span>
          )}
        </div>
      )}

      <div className="flex flex-col gap-3 rounded-[8px] border border-border bg-[var(--color-surface-1)] p-4">
        <div className="flex flex-col gap-1 border-b border-border pb-3">
          <MicroLabel>Subject</MicroLabel>
          <p className="text-sm font-medium text-ink">{subj.text || "—"}</p>
        </div>
        {aiOpener && (
          <div className="flex items-center gap-1.5">
            <Sparkles className="size-3.5 text-review" />
            <StatusChip variant="review" label="AI opener prepended" />
          </div>
        )}
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted">
          {bodyOut.text || "—"}
        </p>
        <UnsubscribeFooter />
      </div>
    </div>
  );
}
