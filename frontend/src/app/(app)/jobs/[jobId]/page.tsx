import { Activity } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default async function JobMonitorPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return (
    <PageStub
      kicker="Mine · Monitor"
      title="Job Run Monitor"
      subtitle={`Live pipeline for job ${jobId}.`}
      icon={Activity}
      actions={
        <>
          <Button size="sm" variant="secondary">
            Pause
          </Button>
          <Button size="sm" variant="danger">
            Cancel
          </Button>
        </>
      }
      emptyTitle="Live run monitor lands here"
      emptyDescription="Per-stage pipeline (resolve → discover → normalize → crawl → extract → enrich → validate → sync) with SSE-driven progress bars, per-queue status, source-run audit log, live totals, and streaming event feed."
    />
  );
}
