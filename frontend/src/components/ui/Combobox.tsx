"use client";

import { useMemo, useState } from "react";
import { Popover, ScrollArea } from "radix-ui";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { baseControl } from "./Input";

export interface ComboboxOption {
  value: string;
  label: string;
}

interface ComboboxProps {
  options: ComboboxOption[];
  /** Selected values (multi-select). */
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  emptyText?: string;
  className?: string;
  invalid?: boolean;
}

/**
 * Multi-select combobox: a control that shows selected values as removable
 * chips and opens a searchable, checkable option list in a Radix Popover.
 */
export function Combobox({
  options,
  value,
  onChange,
  placeholder = "Select…",
  emptyText = "No matches",
  className,
  invalid,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const selected = useMemo(
    () => options.filter((o) => value.includes(o.value)),
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const toggle = (v: string) =>
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            baseControl,
            "flex h-auto min-h-9 flex-wrap items-center gap-1.5 py-1.5 text-left",
            invalid && "border-danger/60",
            className,
          )}
        >
          {selected.length === 0 ? (
            <span className="text-muted/70">{placeholder}</span>
          ) : (
            selected.map((o) => (
              <span
                key={o.value}
                className="inline-flex items-center gap-1 rounded-[6px] border border-border bg-panel px-1.5 py-0.5 text-xs text-ink"
              >
                {o.label}
                <span
                  role="button"
                  tabIndex={-1}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(o.value);
                  }}
                  className="text-muted hover:text-danger"
                >
                  <X className="size-3" />
                </span>
              </span>
            ))
          )}
          <ChevronDown className="ml-auto size-4 shrink-0 text-muted" />
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-[var(--radix-popover-trigger-width)] overflow-hidden rounded-[10px] border border-border bg-[var(--color-surface-2)] shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
        >
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="size-4 text-muted" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted/70"
            />
          </div>
          <ScrollArea.Root className="max-h-56 overflow-hidden">
            <ScrollArea.Viewport className="max-h-56 w-full lm-scroll">
              {filtered.length === 0 ? (
                <p className="px-3 py-4 text-center text-xs text-muted">{emptyText}</p>
              ) : (
                <ul className="p-1">
                  {filtered.map((o) => {
                    const isSel = value.includes(o.value);
                    return (
                      <li key={o.value}>
                        <button
                          type="button"
                          onClick={() => toggle(o.value)}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 rounded-[6px] px-2 py-1.5 text-sm",
                            "text-muted hover:bg-panel hover:text-ink",
                            isSel && "text-ink",
                          )}
                        >
                          {o.label}
                          {isSel && <Check className="size-4 text-accent" />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </ScrollArea.Viewport>
          </ScrollArea.Root>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
