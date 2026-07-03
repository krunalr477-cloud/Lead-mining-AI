"use client";

import { Switch as RadixSwitch } from "radix-ui";
import { cn } from "@/lib/cn";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}

/** Accent toggle switch (radix). Colocated with outreach screens. */
export function Switch({
  checked,
  onCheckedChange,
  disabled,
  id,
  ...rest
}: SwitchProps) {
  return (
    <RadixSwitch.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors lm-focus",
        "border-border bg-[var(--color-surface-1)]",
        "data-[state=checked]:border-[var(--color-accent)]/50 data-[state=checked]:bg-[var(--color-accent)]/20",
        "disabled:opacity-50",
      )}
      {...rest}
    >
      <RadixSwitch.Thumb
        className={cn(
          "block size-3.5 translate-x-0.5 rounded-full bg-muted transition-transform",
          "data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent",
          "data-[state=checked]:shadow-[0_0_8px_var(--color-accent)]",
        )}
      />
    </RadixSwitch.Root>
  );
}
