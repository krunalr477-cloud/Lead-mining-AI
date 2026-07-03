"use client";

import { useState, type ReactNode } from "react";
import { Dialog } from "radix-ui";
import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { LeftRail } from "./LeftRail";
import { TopBar } from "./TopBar";

/**
 * AppShell — persistent chrome for every authenticated screen.
 *  - >=lg: left icon rail (collapsible to 240px), sticky top bar, scrollable main.
 *  - <lg:  rail collapses into a hamburger that opens a Radix Dialog sheet.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="relative z-10 flex min-h-screen w-full">
      {/* Desktop rail */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 border-r border-border bg-[color-mix(in_srgb,var(--color-bg-1)_90%,transparent)] backdrop-blur-md transition-[width] duration-200 lg:flex lg:flex-col",
          expanded ? "w-60" : "w-16",
        )}
      >
        <LeftRail expanded={expanded} />
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "m-2 flex items-center gap-2 rounded-[8px] px-2 py-2 text-muted hover:bg-panel hover:text-ink lm-focus",
            expanded ? "justify-start" : "justify-center",
          )}
          aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
        >
          {expanded ? (
            <>
              <PanelLeftClose className="size-4" />
              <span className="font-mono text-[11px] uppercase tracking-wider">Collapse</span>
            </>
          ) : (
            <PanelLeftOpen className="size-4" />
          )}
        </button>
      </aside>

      {/* Mobile sheet */}
      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-[var(--color-surface-2)] lg:hidden"
          >
            <Dialog.Title className="sr-only">Navigation</Dialog.Title>
            <div className="flex items-center justify-end px-2 pt-2">
              <Dialog.Close
                className="rounded-[6px] p-1.5 text-muted hover:bg-panel hover:text-ink"
                aria-label="Close navigation"
              >
                <X className="size-4" />
              </Dialog.Close>
            </div>
            <LeftRail expanded onNavigate={() => setMobileOpen(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="flex-1 px-3 py-4 sm:px-5 sm:py-6">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
