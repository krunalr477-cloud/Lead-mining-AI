"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Tooltip } from "radix-ui";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { NAV_GROUPS, isNavItemActive, type NavItem } from "./nav";

interface LeftRailProps {
  /** Expanded (240px w/ labels) vs collapsed (icon rail). */
  expanded: boolean;
  /** Called when a nav item is clicked (used to close the mobile sheet). */
  onNavigate?: () => void;
}

/**
 * Left navigation rail. Collapsed = 64px icon rail with tooltips; expanded =
 * 240px with grouped mono section labels + text links.
 */
export function LeftRail({ expanded, onNavigate }: LeftRailProps) {
  const pathname = usePathname();

  return (
    <nav
      className={cn(
        "flex h-full flex-col gap-6 overflow-y-auto py-4 lm-scroll",
        expanded ? "w-60 px-3" : "w-16 items-center px-2",
      )}
      aria-label="Primary"
    >
      <Link
        href="/dashboard"
        onClick={onNavigate}
        className={cn("flex items-center gap-2.5 px-2", expanded ? "" : "justify-center")}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-accent text-[#04120C] shadow-[0_0_16px_-2px_rgba(0,240,168,0.6)]">
          <span className="font-mono text-sm font-bold">L</span>
        </span>
        {expanded && (
          <span className="flex flex-col leading-tight">
            <span className="text-sm font-semibold text-ink">LeadMine</span>
            <MicroLabel className="text-accent/70">AI</MicroLabel>
          </span>
        )}
      </Link>

      <div className="flex w-full flex-1 flex-col gap-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex w-full flex-col gap-1">
            {expanded && <MicroLabel className="px-2 pb-1">{group.label}</MicroLabel>}
            {group.items.map((item) => (
              <RailLink
                key={item.href}
                item={item}
                active={isNavItemActive(item, pathname)}
                expanded={expanded}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ))}
      </div>
    </nav>
  );
}

function RailLink({
  item,
  active,
  expanded,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  expanded: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-[8px] text-sm transition-colors lm-focus",
        expanded ? "px-2.5 py-2" : "size-10 justify-center",
        active
          ? "bg-panel-strong text-ink"
          : "text-muted hover:bg-panel hover:text-ink",
      )}
    >
      {active && (
        <span
          className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent"
          style={{ boxShadow: "0 0 8px var(--color-accent)" }}
          aria-hidden
        />
      )}
      <Icon className={cn("size-5 shrink-0", active && "text-accent")} />
      {expanded && <span className="truncate">{item.label}</span>}
    </Link>
  );

  if (expanded) return link;

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="right"
          sideOffset={8}
          className="z-[60] rounded-[6px] border border-border bg-[var(--color-surface-2)] px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-ink shadow-lg"
        >
          {item.label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
