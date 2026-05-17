import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";

type EvaluationRunDetailRoutePageProps = {
  params: {
    runId: string;
  };
};

export default function EvaluationRunDetailRoutePage({ params }: EvaluationRunDetailRoutePageProps) {
  return <EvaluationsPage initialRunId={params.runId} />;
}
