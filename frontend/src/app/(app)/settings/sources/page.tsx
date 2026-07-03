import { ShieldCheck } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";
import { ComplianceBadge } from "@/components/ui/ComplianceBadge";

export default function SourcesSettingsPage() {
  return (
    <Panel>
      <PanelHeader
        actions={
          <div className="hidden items-center gap-2 sm:flex">
            <ComplianceBadge posture="official" />
            <ComplianceBadge posture="gated" />
            <ComplianceBadge posture="disabled" />
          </div>
        }
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Data Source Compliance</h2>
      </PanelHeader>
      <EmptyState
        icon={ShieldCheck}
        kicker="Coming in this screen"
        title="Source compliance controls land here"
        description="Per-source enable/disable with compliance posture, legal notes, and admin sign-off gates. Amber/red sources (Yellow Pages, Clutch, Indeed, Facebook, LinkedIn) stay disabled until legal review. No authenticated or private scraping is ever permitted."
      />
    </Panel>
  );
}
