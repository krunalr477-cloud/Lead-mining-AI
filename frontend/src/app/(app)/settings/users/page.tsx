import { Users } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";

export default function UsersSettingsPage() {
  return (
    <Panel>
      <PanelHeader actions={<Button size="sm">Invite User</Button>}>
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Users & Roles</h2>
      </PanelHeader>
      <EmptyState
        icon={Users}
        kicker="Coming in this screen"
        title="User & role management lands here"
        description="A member table with RBAC roles — Admin, Sales Manager, Sales Executive, Viewer — plus invitations and per-role permission summaries scoping access to jobs, campaigns, sheets, exports, and dispositions."
      />
    </Panel>
  );
}
