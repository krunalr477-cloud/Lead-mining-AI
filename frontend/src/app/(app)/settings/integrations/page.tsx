import { Plug } from "lucide-react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { EmptyState } from "@/components/ui/EmptyState";

export default function IntegrationsSettingsPage() {
  return (
    <Panel>
      <PanelHeader>
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Integrations & API Keys</h2>
      </PanelHeader>
      <EmptyState
        icon={Plug}
        kicker="Coming in this screen"
        title="Integration cards land here"
        description="Connect and test Google OAuth, Maps, Sheets, Gmail, RocketReach, MillionVerifier, Groq, and the SERP/Jobs provider — each card showing live/mock status, scopes, last-verified time, and a Test button. Keys are stored server-side only."
      />
    </Panel>
  );
}
