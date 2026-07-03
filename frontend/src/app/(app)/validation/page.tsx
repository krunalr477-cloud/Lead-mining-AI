import { ValidationView } from "./validation-view";

export default async function ValidationPage({
  searchParams,
}: {
  searchParams: Promise<{ job?: string }>;
}) {
  const { job } = await searchParams;
  return <ValidationView initialJobId={job} />;
}
