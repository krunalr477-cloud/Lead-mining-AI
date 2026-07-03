"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plug, SlidersHorizontal, ShieldCheck, Users, ScrollText } from "lucide-react";
import type { LucideProps } from "lucide-react";
import type { ComponentType } from "react";
import { cn } from "@/lib/cn";

interface SettingsLink {
  label: string;
  href: string;
  icon: ComponentType<LucideProps>;
}

const LINKS: SettingsLink[] = [
  { label: "Integrations", href: "/settings/integrations", icon: Plug },
  { label: "Validation Rules", href: "/settings/validation", icon: SlidersHorizontal },
  { label: "Data Sources", href: "/settings/sources", icon: ShieldCheck },
  { label: "Users & Roles", href: "/settings/users", icon: Users },
  { label: "Audit Logs", href: "/settings/audit", icon: ScrollText },
];

export function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1" aria-label="Settings">
      {LINKS.map((l) => {
        const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
        const Icon = l.icon;
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-sm transition-colors lm-focus",
              active ? "bg-panel-strong text-ink" : "text-muted hover:bg-panel hover:text-ink",
            )}
          >
            <Icon className={cn("size-4 shrink-0", active && "text-accent")} />
            <span className="truncate">{l.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
