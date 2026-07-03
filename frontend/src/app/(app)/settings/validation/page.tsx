import { SlidersHorizontal } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";

export default function ValidationSettingsPage() {
  return (
    <Panel>
      <PanelHeader>
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Validation Rules</h2>
      </PanelHeader>
      <EmptyState
        icon={SlidersHorizontal}
        kicker="Coming in this screen"
        title="Validation rule controls land here"
        description="Editable disposable-domain list, role-based keyword list, LLM confidence threshold, catch-all handling, risk handling, and the unknown-retry policy — the knobs that decide which emails may enter Sales_Ready_Leads."
      />
    </Panel>
  );
}
