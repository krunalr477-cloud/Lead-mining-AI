"use client";

import { createContext, useContext, type ReactNode, type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * Panel — the thin glass-like surface that everything sits in. Composed of:
 *   <Panel>            outer surface (border + elevated fill)
 *     <Panel.Header>   title row, bottom border divider
 *     <Panel.Section>  content region, divided by borders (NOT nested panels)
 *
 * PROHIBITION: no nested cards. A dev-time guard warns if a <Panel> renders
 * inside another <Panel> so the "avoid nested cards" rule is enforced during
 * development. Use Panel.Section (border dividers) to subdivide instead.
 */

const PanelDepthContext = createContext(0);

interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Remove default padding (e.g. when wrapping a full-bleed DataTable). */
  flush?: boolean;
}

function PanelRoot({ className, children, flush = false, ...props }: PanelProps) {
  const depth = useContext(PanelDepthContext);

  if (process.env.NODE_ENV !== "production" && depth > 0) {
    console.warn(
      "[LeadMine] Nested <Panel> detected. Avoid nested cards — use <Panel.Section> " +
        "with border dividers to subdivide a panel instead.",
    );
  }

  return (
    <PanelDepthContext.Provider value={depth + 1}>
      <div
        className={cn(
          "relative rounded-[14px] border border-border bg-panel",
          "shadow-[0_1px_0_rgba(255,255,255,0.03)_inset,0_10px_30px_-20px_rgba(0,0,0,0.8)]",
          "backdrop-blur-[2px]",
          !flush && "p-4 sm:p-5",
          className,
        )}
        {...props}
      >
        {children}
      </div>
    </PanelDepthContext.Provider>
  );
}

interface PanelHeaderProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Right-aligned actions (buttons, chips). */
  actions?: ReactNode;
}

function PanelHeader({ className, children, actions, ...props }: PanelHeaderProps) {
  return (
    <div
      className={cn(
        "-mx-4 -mt-4 mb-4 flex items-center justify-between gap-3 border-b border-border px-4 pb-3 pt-0 sm:-mx-5 sm:-mt-5 sm:px-5",
        className,
      )}
      {...props}
    >
      <div className="flex min-w-0 flex-col gap-0.5">{children}</div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

interface PanelSectionProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Add a top border divider (for stacking sections). */
  divided?: boolean;
}

function PanelSection({ className, children, divided = false, ...props }: PanelSectionProps) {
  return (
    <div
      className={cn(
        divided && "-mx-4 mt-4 border-t border-border px-4 pt-4 sm:-mx-5 sm:px-5",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * Compound API for ergonomic client-component usage: `<Panel><Panel.Header/>…`.
 *
 * IMPORTANT: the `Panel.Header` / `Panel.Section` dot-access only works inside
 * *client* components. When a *Server Component* needs these, import the named
 * exports `PanelHeader` / `PanelSection` instead — property access on a client
 * reference is stripped across the RSC boundary and would resolve to undefined.
 */
export const Panel = Object.assign(PanelRoot, {
  Header: PanelHeader,
  Section: PanelSection,
});

export { PanelHeader, PanelSection };
