import { Inbox } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function BouncesPage() {
  return (
    <PageStub
      kicker="Reach"
      title="Bounce & Reply Monitor"
      subtitle="Delivery failures and replies from inbox polling."
      icon={Inbox}
      actions={<Button size="sm" variant="secondary">Poll Now</Button>}
      emptyTitle="Bounce & reply monitor lands here"
      emptyDescription="A DataTable of bounces and replies with SMTP status code, bounce classification (hard/soft, mailbox full, blocked, spam-rejected), reason, matched contact, and one-click suppression actions that update the DB and Google Sheets."
    />
  );
}
