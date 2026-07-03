import { ShieldCheck } from "lucide-react";
import { PageStub } from "@/components/shell/PageStub";
import { Button } from "@/components/ui/Button";

export default function ValidationPage() {
  return (
    <PageStub
      kicker="Mine"
      title="Validation Pipeline"
      subtitle="Per-stage email verification results."
      icon={ShieldCheck}
      actions={<Button size="sm" variant="secondary">Revalidate Selected</Button>}
      emptyTitle="Validation pipeline lands here"
      emptyDescription="A DataTable where each validation stage is a column — syntax, disposable, role-based, MX, LLM score, MillionVerifier — with pass/fail/review per stage, the final decision chip, and bulk revalidation of selected emails."
    />
  );
}
