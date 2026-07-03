import { Send } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function CampaignsPage() {
  return (
    <PageStub
      kicker="Reach"
      title="Campaigns"
      subtitle="Outreach campaigns across verified audiences."
      icon={Send}
      actions={<Button size="sm">New Campaign</Button>}
      emptyTitle="Campaign list lands here"
      emptyDescription="A DataTable of campaigns with recipient/sent/delivered/open/click/reply/bounce counts, status chips (draft, scheduled, sending, paused, completed), attached job, and from-account — each linking to its detail and performance view."
    />
  );
}
