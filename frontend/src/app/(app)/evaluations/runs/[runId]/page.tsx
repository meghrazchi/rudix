import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";

type EvaluationRunDetailRoutePageProps = {
  params: Promise<{
    runId: string;
  }>;
};

export default async function EvaluationRunDetailRoutePage({
  params,
}: EvaluationRunDetailRoutePageProps) {
  const { runId } = await params;

  return <EvaluationsPage initialRunId={runId} />;
}
