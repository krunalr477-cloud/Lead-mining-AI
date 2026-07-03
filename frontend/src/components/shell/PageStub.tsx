import type { ComponentType, ReactNode } from "react";
import type { LucideProps } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";

interface PageStubProps {
  /** Mono kicker (section family). */
  kicker: string;
  /** Panel title (screen name). */
  title: string;
  /** One-line summary under the title. */
  subtitle?: string;
  /** EmptyState config describing what lands here. */
  icon?: ComponentType<LucideProps>;
  emptyTitle: string;
  emptyDescription: ReactNode;
  /** Optional header actions. */
  actions?: ReactNode;
  /** Optional extra content rendered above the empty state. */
  children?: ReactNode;
}

/**
 * Shared foundation stub: a single Panel with a mono-labelled header and an
 * EmptyState describing the screen's eventual content. Every one of the 19
 * routes renders through this so the app is fully navigable now and each screen
 * self-documents what it will become.
 *
 * Kept as a Server Component and using the named PanelHeader export so pages can
 * pass a lucide icon *component* directly without crossing an RSC boundary.
 */
export function PageStub({
  kicker,
  title,
  subtitle,
  icon,
  emptyTitle,
  emptyDescription,
  actions,
  children,
}: PageStubProps) {
  return (
    <div className="flex flex-col gap-4">
      <Panel>
        <PanelHeader actions={actions}>
          <MicroLabel className="text-accent/70">{kicker}</MicroLabel>
          <h1 className="text-lg font-semibold text-ink">{title}</h1>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </PanelHeader>
        {children}
        <EmptyState
          icon={icon}
          kicker="Coming in this screen"
          title={emptyTitle}
          description={emptyDescription}
        />
      </Panel>
    </div>
  );
}
