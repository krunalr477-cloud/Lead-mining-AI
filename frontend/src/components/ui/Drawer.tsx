"use client";

import { createContext, useContext, type ReactNode } from "react";
import { Dialog } from "radix-ui";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "./MicroLabel";

/**
 * Drawer — Radix Dialog rendered as a right-side sheet on desktop and a
 * bottom sheet on mobile. Supports STACKING: nested drawers offset slightly and
 * dim the one beneath. Depth is tracked via context and drives the offset +
 * overlay opacity so opening a second drawer reads as "on top of" the first.
 */

const DrawerDepthContext = createContext(0);

interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function DrawerRoot({ open, onOpenChange, children }: DrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      {children}
    </Dialog.Root>
  );
}

interface DrawerContentProps {
  children: ReactNode;
  /** Mono kicker + title in the header. */
  title?: string;
  kicker?: string;
  /** Header right-side actions. */
  actions?: ReactNode;
  className?: string;
  /** Sheet width on desktop. */
  width?: "sm" | "md" | "lg";
}

const WIDTHS: Record<NonNullable<DrawerContentProps["width"]>, string> = {
  sm: "lg:max-w-sm",
  md: "lg:max-w-md",
  lg: "lg:max-w-xl",
};

function DrawerContent({
  children,
  title,
  kicker,
  actions,
  className,
  width = "md",
}: DrawerContentProps) {
  const depth = useContext(DrawerDepthContext);
  const offset = Math.min(depth, 3) * 24;

  return (
    <Dialog.Portal>
      <Dialog.Overlay
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=open]:fade-in"
        style={{ opacity: depth > 0 ? 0.4 : undefined }}
      />
      <Dialog.Content
        aria-describedby={undefined}
        style={{ marginRight: offset ? `${offset}px` : undefined }}
        className={cn(
          "fixed z-50 flex flex-col border-border bg-[var(--color-surface-2)] shadow-[0_0_60px_-15px_rgba(0,0,0,0.9)] lm-scroll",
          // Mobile: bottom sheet
          "inset-x-0 bottom-0 max-h-[88vh] rounded-t-[16px] border-t",
          // Desktop: right sheet
          "lg:inset-y-0 lg:right-0 lg:bottom-auto lg:left-auto lg:max-h-none lg:w-full lg:rounded-none lg:rounded-l-[16px] lg:border-l lg:border-t-0",
          WIDTHS[width],
          className,
        )}
      >
        <DrawerDepthContext.Provider value={depth + 1}>
          {(title || kicker || actions) && (
            <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex min-w-0 flex-col gap-1">
                {kicker && <MicroLabel className="text-accent/80">{kicker}</MicroLabel>}
                {title && (
                  <Dialog.Title className="truncate text-base font-semibold text-ink">
                    {title}
                  </Dialog.Title>
                )}
              </div>
              <div className="flex items-center gap-2">
                {actions}
                <Dialog.Close
                  className="rounded-[6px] p-1 text-muted transition-colors hover:bg-panel hover:text-ink lm-focus"
                  aria-label="Close"
                >
                  <X className="size-4" />
                </Dialog.Close>
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto px-5 py-4 lm-scroll">{children}</div>
        </DrawerDepthContext.Provider>
      </Dialog.Content>
    </Dialog.Portal>
  );
}

export const Drawer = Object.assign(DrawerRoot, {
  Trigger: Dialog.Trigger,
  Content: DrawerContent,
  Close: Dialog.Close,
});
