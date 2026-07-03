"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Slot } from "radix-ui";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[8px]",
    "font-medium transition-colors select-none lm-focus",
    "disabled:pointer-events-none disabled:opacity-45",
  ),
  {
    variants: {
      variant: {
        // Primary: accent bg, black text, subtle green glow.
        primary:
          "bg-accent text-[#04120C] hover:bg-[var(--color-accent-2)] shadow-[0_0_0_1px_rgba(0,240,168,0.25),0_6px_20px_-8px_rgba(0,240,168,0.55)]",
        // Secondary: bordered, transparent fill.
        secondary:
          "border border-[var(--color-border-strong)] bg-panel text-ink hover:bg-[var(--color-panel-strong)] hover:border-[var(--color-accent)]/50",
        // Ghost: text only.
        ghost: "text-muted hover:text-ink hover:bg-panel",
        // Danger: red bordered.
        danger:
          "border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 text-[var(--color-danger)] hover:bg-[var(--color-danger)]/20",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-sm",
        lg: "h-11 px-6 text-sm",
        icon: "size-9 p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as child (Radix Slot) to compose with <a>/<Link>. */
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, loading = false, disabled, children, ...props },
  ref,
) {
  const Comp = asChild ? Slot.Root : "button";

  // In asChild mode, Radix Slot requires exactly one React element child, so we
  // must NOT emit the (possibly `false`) loading node alongside it — that yields
  // "Expected a single React element child". Pass children straight through; the
  // spinner is only meaningful for real <button> usage anyway.
  if (asChild) {
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...props}
      >
        {children}
      </Comp>
    );
  }

  return (
    <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </Comp>
  );
});

export { buttonVariants };
