import { ResultsView } from "./results-view";

export default async function JobResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <ResultsView jobId={jobId} />;
}
