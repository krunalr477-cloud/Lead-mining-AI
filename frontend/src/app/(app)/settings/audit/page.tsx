import { ScrollText } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";

export default function AuditSettingsPage() {
  return (
    <Panel>
      <PanelHeader>
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Audit Logs</h2>
      </PanelHeader>
      <EmptyState
        icon={ScrollText}
        kicker="Coming in this screen"
        title="Audit log lands here"
        description="A searchable, filterable DataTable of every mutation — actor, action, entity type/ID, before/after values, and timestamp — for compliance and forensics across jobs, sheets sync, sources, and settings."
      />
    </Panel>
  );
}
