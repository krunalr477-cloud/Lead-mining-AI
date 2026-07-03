import { Radar } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";

export default function NewJobPage() {
  return (
    <PageStub
      kicker="Mine"
      title="New Mining Job"
      subtitle="Configure sources, geography, roles, and validation."
      icon={Radar}
      emptyTitle="Job builder lands here"
      emptyDescription="Split layout: left form (company type, services, geography, size, contact roles, exclude keywords, compliance-gated source chips, enrichment & validation options), center interactive Google Map with a draggable pin and editable radius, and a right estimate/compliance panel — with a neon Start Mining CTA."
    />
  );
}
