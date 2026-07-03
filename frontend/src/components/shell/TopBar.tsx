"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment } from "react";
import { DropdownMenu } from "radix-ui";
import { ChevronRight, LogOut, Menu, User as UserIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { useSession } from "@/lib/auth/session";
import { api } from "@/lib/api/client";
import { SEGMENT_LABELS } from "./nav";
import { DemoRibbon } from "./DemoRibbon";

interface Crumb {
  label: string;
  href: string;
}

function buildCrumbs(pathname: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: Crumb[] = [];
  let acc = "";
  for (const seg of segments) {
    acc += `/${seg}`;
    // Dynamic id segments render as a short mono token.
    const isId = !SEGMENT_LABELS[seg] && /[0-9]/.test(seg);
    crumbs.push({
      label: isId ? `#${seg.slice(0, 8)}` : SEGMENT_LABELS[seg] ?? seg,
      href: acc,
    });
  }
  return crumbs;
}

interface TopBarProps {
  /** Toggle the mobile nav sheet (rendered below lg). */
  onOpenMobileNav: () => void;
}

export function TopBar({ onOpenMobileNav }: TopBarProps) {
  const pathname = usePathname();
  const { user, tenant } = useSession();
  const crumbs = buildCrumbs(pathname);

  const logout = async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      window.location.href = "/login";
    }
  };

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-[color-mix(in_srgb,var(--color-bg-1)_88%,transparent)] px-3 backdrop-blur-md sm:px-5">
      <button
        type="button"
        onClick={onOpenMobileNav}
        className="rounded-[8px] p-1.5 text-muted hover:bg-panel hover:text-ink lm-focus lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <Fragment key={c.href}>
              {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted/50" />}
              {last ? (
                <span className="truncate text-sm font-medium text-ink">{c.label}</span>
              ) : (
                <Link
                  href={c.href}
                  className="hidden truncate text-sm text-muted hover:text-ink sm:inline"
                >
                  {c.label}
                </Link>
              )}
            </Fragment>
          );
        })}
      </nav>

      <div className="flex items-center gap-3">
        <DemoRibbon />

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              className="flex items-center gap-2 rounded-[8px] border border-border bg-panel px-2 py-1.5 text-left hover:border-[var(--color-border-strong)] lm-focus"
            >
              <span className="flex size-6 items-center justify-center rounded-full bg-[var(--color-surface-2)] text-accent">
                <UserIcon className="size-3.5" />
              </span>
              <span className="hidden flex-col leading-tight sm:flex">
                <span className="max-w-[120px] truncate text-xs font-medium text-ink">
                  {user?.name ?? "Signed out"}
                </span>
                <MicroLabel className="text-[10px]">{tenant?.name ?? "—"}</MicroLabel>
              </span>
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={8}
              className="z-[70] w-56 rounded-[10px] border border-border bg-[var(--color-surface-2)] p-1.5 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]"
            >
              <div className="px-2 py-2">
                <p className="truncate text-sm font-medium text-ink">{user?.name ?? "—"}</p>
                <p className="truncate text-xs text-muted">{user?.email ?? "—"}</p>
                {user?.role && (
                  <MicroLabel className="mt-1 inline-block text-accent/80">
                    {user.role.replace("_", " ")}
                  </MicroLabel>
                )}
              </div>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item asChild>
                <Link
                  href="/settings/users"
                  className={cn(
                    "flex items-center gap-2 rounded-[6px] px-2 py-1.5 text-sm text-muted outline-none",
                    "data-[highlighted]:bg-panel data-[highlighted]:text-ink",
                  )}
                >
                  <UserIcon className="size-4" />
                  Account & Roles
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Item
                onSelect={logout}
                className="flex items-center gap-2 rounded-[6px] px-2 py-1.5 text-sm text-danger outline-none data-[highlighted]:bg-[var(--color-danger)]/10"
              >
                <LogOut className="size-4" />
                Sign out
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
  );
}
