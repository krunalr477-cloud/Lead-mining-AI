import { Send } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default async function CampaignDetailPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = await params;
  return (
    <PageStub
      kicker="Reach · Campaign"
      title="Campaign Detail"
      subtitle={`Performance and controls for campaign ${campaignId}.`}
      icon={Send}
      actions={
        <>
          <Button size="sm" variant="secondary">Pause</Button>
          <Button size="sm" variant="danger">Cancel</Button>
        </>
      }
      emptyTitle="Campaign detail lands here"
      emptyDescription="Performance chart (sent, delivered, opened, clicked, replied, bounced), recipient queue with per-message states and Gmail message IDs, rate-limit progress, estimated completion, and pause/resume/cancel controls."
    />
  );
}
