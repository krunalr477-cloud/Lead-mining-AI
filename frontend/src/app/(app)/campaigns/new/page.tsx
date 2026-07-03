import { Send } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";

export default function NewCampaignPage() {
  return (
    <PageStub
      kicker="Reach"
      title="Campaign Builder"
      subtitle="Compose and target a new outreach campaign."
      icon={Send}
      emptyTitle="Campaign builder lands here"
      emptyDescription="Subject/body editor with a variable insertion menu, per-contact preview, optional AI opener toggle, from-account selector, per-hour/day rate limits and send window, recipient-eligibility summary (verified only), suppression check, unsubscribe footer, test send, and launch controls."
    />
  );
}
