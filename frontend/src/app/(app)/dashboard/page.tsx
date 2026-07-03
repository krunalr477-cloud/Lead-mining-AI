import { LayoutDashboard } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function DashboardPage() {
  return (
    <PageStub
      kicker="Overview"
      title="Dashboard"
      subtitle="Live command center for mining, validation, and outreach."
      icon={LayoutDashboard}
      actions={<Button size="sm">New Mining Job</Button>}
      emptyTitle="Command-center dashboard lands here"
      emptyDescription="Top metrics strip, live Mine→Verify→Send funnel, active jobs table, campaign performance chart, a clustered mining map, source-health panel, and Google Sheets sync status."
    />
  );
}
