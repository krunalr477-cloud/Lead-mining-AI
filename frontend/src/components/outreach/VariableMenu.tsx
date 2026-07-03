"use client";

import { DropdownMenu } from "radix-ui";
import { Braces, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui";
import { TEMPLATE_VARIABLES } from "./template";
import type { TemplateVariable } from "@/lib/api/schema";

interface VariableMenuProps {
  /** Called with the chosen variable name (e.g. "FirstName"). */
  onInsert: (variable: TemplateVariable) => void;
  disabled?: boolean;
}

/**
 * Radix DropdownMenu of the 12 template variables. Selecting one calls onInsert
 * so the parent can splice `{{Variable}}` in at the current caret position.
 */
export function VariableMenu({ onInsert, disabled }: VariableMenuProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-[6px] border border-border bg-panel px-2 py-1",
            "font-mono text-[11px] uppercase tracking-wider text-muted transition-colors lm-focus",
            "hover:border-[var(--color-accent)]/50 hover:text-ink",
            "disabled:opacity-50",
          )}
        >
          <Braces className="size-3.5" />
          Insert variable
          <ChevronDown className="size-3" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-[70] max-h-[320px] w-52 overflow-y-auto rounded-[10px] border border-border bg-[var(--color-surface-2)] p-1.5 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)] lm-scroll"
        >
          <div className="px-2 py-1">
            <MicroLabel className="text-accent/70">Template variables</MicroLabel>
          </div>
          {TEMPLATE_VARIABLES.map((v) => (
            <DropdownMenu.Item
              key={v}
              onSelect={() => onInsert(v)}
              className={cn(
                "flex cursor-pointer items-center justify-between rounded-[6px] px-2 py-1.5 text-sm text-muted outline-none",
                "data-[highlighted]:bg-panel data-[highlighted]:text-ink",
              )}
            >
              <span>{v}</span>
              <span className="font-mono text-[10px] text-muted/60">{`{{${v}}}`}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
