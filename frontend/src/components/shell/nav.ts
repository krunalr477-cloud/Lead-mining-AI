import type { ComponentType } from "react";
import {
  LayoutDashboard,
  Radar,
  ShieldCheck,
  Sheet,
  Send,
  Inbox,
  Download,
  Settings,
  History,
  HelpCircle,
  type LucideProps,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: ComponentType<LucideProps>;
  /** Prefixes that should mark this item active (beyond exact href). */
  matches?: string[];
}

export interface NavGroup {
  /** Mono section label rendered when the rail is expanded. */
  label: string;
  items: NavItem[];
}

/** Primary left-rail navigation, grouped by workflow phase. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Mine",
    items: [
      { label: "Jobs", href: "/jobs", icon: Radar, matches: ["/jobs"] },
      { label: "Validation", href: "/validation", icon: ShieldCheck },
      { label: "Sheets Sync", href: "/sheets", icon: Sheet },
    ],
  },
  {
    label: "Reach",
    items: [
      { label: "Campaigns", href: "/campaigns", icon: Send, matches: ["/campaigns"] },
      { label: "Outreach", href: "/outreach", icon: History },
      { label: "Bounces", href: "/bounces", icon: Inbox },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Exports", href: "/exports", icon: Download },
      { label: "Settings", href: "/settings", icon: Settings, matches: ["/settings"] },
      { label: "Help", href: "/help", icon: HelpCircle },
    ],
  },
];

/** Flat list for breadcrumb/label lookups. */
export const NAV_FLAT: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

/** Human labels for path segments used by the breadcrumb builder. */
export const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  jobs: "Jobs",
  new: "New",
  results: "Results",
  validation: "Validation",
  sheets: "Sheets Sync",
  campaigns: "Campaigns",
  outreach: "Outreach",
  bounces: "Bounces",
  exports: "Exports",
  settings: "Settings",
  help: "Info & Help",
  integrations: "Integrations",
  sources: "Data Sources",
  users: "Users & Roles",
  audit: "Audit Logs",
};

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (pathname === item.href) return true;
  const prefixes = item.matches ?? [item.href];
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
