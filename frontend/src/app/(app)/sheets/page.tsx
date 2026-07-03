import { Sheet } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function SheetsPage() {
  return (
    <PageStub
      kicker="Mine"
      title="Google Sheets Sync"
      subtitle="Sales-facing system of record status."
      icon={Sheet}
      actions={
        <>
          <Button size="sm" variant="secondary">Sync Now</Button>
          <Button size="sm">Open Google Sheet</Button>
        </>
      }
      emptyTitle="Sheets sync monitor lands here"
      emptyDescription="Connected spreadsheet, per-tab status (Mining_Jobs, Companies, Contacts, Email_Validation, Sales_Ready_Leads, Outreach_Queue, Campaigns, Bounce_Log, and more), last-sync timestamps, failed-row list with retry controls, and an Open Google Sheet button."
    />
  );
}
