import type { ReactNode } from "react";
import { Panel } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { SettingsNav } from "./SettingsNav";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <MicroLabel className="text-accent/70">System</MicroLabel>
        <h1 className="text-lg font-semibold text-ink">Settings</h1>
        <p className="text-sm text-muted">
          Integrations, validation rules, source compliance, users, and audit.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
        <Panel className="h-fit lg:sticky lg:top-20">
          <SettingsNav />
        </Panel>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
