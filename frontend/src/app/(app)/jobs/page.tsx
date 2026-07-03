import { Radar } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function JobsPage() {
  return (
    <PageStub
      kicker="Mine"
      title="Job History"
      subtitle="Every mining run — searchable and auditable."
      icon={Radar}
      actions={<Button size="sm">New Mining Job</Button>}
      emptyTitle="Searchable job history lands here"
      emptyDescription="A DataTable of every mining job with name, creator, location, sources, status, company/contact/verified/sales-ready counts, attached campaign, duration, and errors — filterable by name, type, location, source, status, date range, and creator."
    />
  );
}
