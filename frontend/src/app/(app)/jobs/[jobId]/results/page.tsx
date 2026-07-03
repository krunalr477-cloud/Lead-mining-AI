import { Table2 } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default async function JobResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return (
    <PageStub
      kicker="Mine · Results"
      title="Mining Results"
      subtitle={`Companies and contacts discovered by job ${jobId}.`}
      icon={Table2}
      actions={<Button size="sm" variant="secondary">Export</Button>}
      emptyTitle="Mining results table lands here"
      emptyDescription="Summary counters (companies, contacts, emails found, verified, review, invalid) and a filterable DataTable — company, city, rating, contact, role, email, validation status, source, sales-ready — with source/status/role/city filters and a row drawer showing company & contact evidence."
    />
  );
}
