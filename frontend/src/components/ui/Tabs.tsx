"use client";

import { Tabs as RadixTabs } from "radix-ui";
import { cn } from "@/lib/cn";

/**
 * Tabs — thin wrapper over Radix Tabs with the LeadMine underline treatment.
 * Compose: <Tabs><TabsList><TabsTrigger/></TabsList><TabsContent/></Tabs>.
 */
export const Tabs = RadixTabs.Root;

export function TabsList({ className, ...props }: RadixTabs.TabsListProps) {
  return (
    <RadixTabs.List
      className={cn("flex items-center gap-1 border-b border-border", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: RadixTabs.TabsTriggerProps) {
  return (
    <RadixTabs.Trigger
      className={cn(
        "relative -mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted transition-colors lm-focus",
        "hover:text-ink",
        "data-[state=active]:border-[var(--color-accent)] data-[state=active]:text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: RadixTabs.TabsContentProps) {
  return <RadixTabs.Content className={cn("pt-4 lm-focus", className)} {...props} />;
}
