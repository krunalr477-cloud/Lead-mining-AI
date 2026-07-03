"use client";

import { useState, type KeyboardEvent } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { baseControl } from "@/components/ui/Input";

/* ─────────────────────────────────────────────────────────────────────────
 * ChipToggleGroup — a set of preset options rendered as toggleable chips.
 * Used for services and contact roles. Each option can carry a `warn` flag
 * (e.g. HR/Recruiting) that renders an amber tint + shows a note when active.
 * ───────────────────────────────────────────────────────────────────────── */

export interface ChipOption {
  value: string;
  label: string;
  /** Render with a caution tint and surface `warnNote` when selected. */
  warn?: boolean;
}

export function ChipToggleGroup({
  options,
  value,
  onChange,
  warnNote,
}: {
  options: ChipOption[];
  value: string[];
  onChange: (next: string[]) => void;
  warnNote?: string;
}) {
  const toggle = (v: string) =>
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);

  const anyWarnActive = options.some((o) => o.warn && value.includes(o.value));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const active = value.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={active}
              onClick={() => toggle(o.value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors lm-focus",
                active
                  ? o.warn
                    ? "border-[var(--color-warn)]/50 bg-[var(--color-warn)]/12 text-[var(--color-warn)]"
                    : "border-[var(--color-accent)]/50 bg-[var(--color-accent)]/12 text-[var(--color-accent)]"
                  : "border-border bg-panel text-muted hover:border-[var(--color-border-strong)] hover:text-ink",
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      {anyWarnActive && warnNote && (
        <p className="text-xs leading-relaxed text-[var(--color-warn)]">{warnNote}</p>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
 * KeywordChips — free-text chip input. Enter/comma commits a token; each chip
 * has a remove affordance. Used for exclude keywords (pre-seeded) and services.
 * ───────────────────────────────────────────────────────────────────────── */

export function KeywordChips({
  value,
  onChange,
  placeholder = "Type and press Enter…",
  suggestions = [],
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const token = raw.trim();
    if (!token) return;
    if (!value.some((v) => v.toLowerCase() === token.toLowerCase())) {
      onChange([...value, token]);
    }
    setDraft("");
  };

  const remove = (v: string) => onChange(value.filter((x) => x !== v));

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      remove(value[value.length - 1]);
    }
  };

  const openSuggestions = suggestions.filter(
    (s) => !value.some((v) => v.toLowerCase() === s.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-2">
      <div
        className={cn(
          baseControl,
          "flex h-auto min-h-9 flex-wrap items-center gap-1.5 py-1.5",
        )}
      >
        {value.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-[6px] border border-border bg-panel px-1.5 py-0.5 text-xs text-ink"
          >
            {v}
            <button
              type="button"
              onClick={() => remove(v)}
              className="text-muted hover:text-danger"
              aria-label={`Remove ${v}`}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={value.length ? "" : placeholder}
          className="min-w-[8ch] flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted/70"
        />
      </div>
      {openSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {openSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2 py-0.5 text-[11px] text-muted transition-colors hover:border-[var(--color-accent)]/40 hover:text-ink"
            >
              <Plus className="size-3" />
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
 * ToggleRow — a labelled checkbox row for enrichment/validation/output opts.
 * ───────────────────────────────────────────────────────────────────────── */

export function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-[8px] border border-transparent px-1 py-1.5 transition-colors hover:border-border",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="lm-checkbox mt-0.5"
      />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm text-ink">{label}</span>
        {description && (
          <span className="text-xs leading-relaxed text-muted">{description}</span>
        )}
      </span>
    </label>
  );
}
