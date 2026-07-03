import { ListChecks } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";

export default function OutreachPage() {
  return (
    <PageStub
      kicker="Reach"
      title="Outreach Queue"
      subtitle="Scheduled and in-flight sends across campaigns."
      icon={ListChecks}
      emptyTitle="Outreach queue lands here"
      emptyDescription="A DataTable of queued messages — campaign, recipient, company, subject, scheduled/sent time, send status, and per-message tracking (opened, clicked, replied, bounced) — with per-account rate-limit health and suppression guards."
    />
  );
}
