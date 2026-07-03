"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui/MicroLabel";

/**
 * EditableField — click-to-edit inline field used in the contact drawer for
 * owner / sales_notes / next_action.
 *
 *   click value  -> enters edit mode
 *   Enter        -> save (blur commit); Shift+Enter inserts newline in textarea
 *   Esc          -> revert + exit
 *   blur         -> save (if changed)
 *
 * `onSave` should be the OPTIMISTIC mutation (usePatchContact) — this component
 * closes immediately on commit and shows a transient saving spinner while the
 * mutation settles, so the value never flickers back.
 */
interface EditableFieldProps {
  label: string;
  value: string | null | undefined;
  onSave: (next: string) => void | Promise<unknown>;
  placeholder?: string;
  /** Multiline textarea instead of single-line input. */
  multiline?: boolean;
  /** Render value with mono voice (e.g. IDs, emails). */
  mono?: boolean;
  saving?: boolean;
  disabled?: boolean;
  className?: string;
  /** Small hint shown under the field (e.g. "syncs to Google Sheet"). */
  hint?: string;
}

export function EditableField({
  label,
  value,
  onSave,
  placeholder = "Set value…",
  multiline = false,
  mono = false,
  saving = false,
  disabled = false,
  className,
  hint,
}: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);

  // Keep the local draft synced when the upstream value changes and we're idle,
  // derived during render (React's recommended alternative to a setState effect):
  // track the last-seen prop and reconcile before the next paint.
  const [lastValue, setLastValue] = useState(value ?? "");
  if (!editing && (value ?? "") !== lastValue) {
    setLastValue(value ?? "");
    setDraft(value ?? "");
  }

  useEffect(() => {
    if (editing && inputRef.current) {
      const el = inputRef.current;
      el.focus();
      const len = el.value.length;
      el.setSelectionRange(len, len);
    }
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    setEditing(false);
    if (next !== (value ?? "").trim()) {
      void onSave(next);
    }
  };

  const cancel = () => {
    setDraft(value ?? "");
    setEditing(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !(multiline && e.shiftKey)) {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  };

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <MicroLabel>{label}</MicroLabel>
        {saving && (
          <span className="inline-flex items-center gap-1 text-[10px] text-info">
            <Loader2 className="size-3 animate-spin" />
            <span className="font-mono uppercase tracking-wider">Syncing</span>
          </span>
        )}
      </div>

      {editing ? (
        <div className="flex items-start gap-1.5">
          {multiline ? (
            <textarea
              ref={inputRef as React.RefObject<HTMLTextAreaElement>}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              onBlur={commit}
              rows={3}
              placeholder={placeholder}
              className={cn(
                "min-w-0 flex-1 resize-y rounded-[8px] border border-[var(--color-accent)]/50 bg-[var(--color-surface-1)] px-2.5 py-1.5 text-sm text-ink outline-none lm-focus",
                mono && "font-mono",
              )}
            />
          ) : (
            <input
              ref={inputRef as React.RefObject<HTMLInputElement>}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              onBlur={commit}
              placeholder={placeholder}
              className={cn(
                "h-9 min-w-0 flex-1 rounded-[8px] border border-[var(--color-accent)]/50 bg-[var(--color-surface-1)] px-2.5 text-sm text-ink outline-none lm-focus",
                mono && "font-mono",
              )}
            />
          )}
          <div className="flex shrink-0 flex-col gap-1 pt-0.5">
            <button
              type="button"
              // onMouseDown so it fires before the input blur cancels it.
              onMouseDown={(e) => {
                e.preventDefault();
                commit();
              }}
              aria-label="Save"
              className="inline-flex size-6 items-center justify-center rounded-[6px] text-accent hover:bg-panel lm-focus"
            >
              <Check className="size-3.5" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                cancel();
              }}
              aria-label="Cancel"
              className="inline-flex size-6 items-center justify-center rounded-[6px] text-muted hover:bg-panel hover:text-ink lm-focus"
            >
              <X className="size-3.5" />
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => !disabled && setEditing(true)}
          className={cn(
            "group flex min-h-9 w-full items-center justify-between gap-2 rounded-[8px] border border-transparent px-2.5 py-1.5 text-left text-sm transition-colors",
            disabled
              ? "cursor-not-allowed opacity-60"
              : "hover:border-border hover:bg-[var(--color-surface-1)] lm-focus",
          )}
        >
          <span
            className={cn(
              "min-w-0 flex-1 truncate",
              mono && "font-mono",
              value ? "text-ink/90" : "text-muted italic",
            )}
          >
            {value?.trim() ? value : placeholder}
          </span>
          {!disabled && (
            <Pencil className="size-3.5 shrink-0 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
          )}
        </button>
      )}

      {hint && <p className="text-[11px] text-muted/70">{hint}</p>}
    </div>
  );
}
