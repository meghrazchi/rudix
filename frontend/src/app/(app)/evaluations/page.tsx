import { FeaturePlaceholder } from "@/components/layout/FeaturePlaceholder";

export default function EvaluationsPage() {
  return (
    <FeaturePlaceholder
      title="Evaluations"
      summary="Evaluation set management and run analysis for quality monitoring."
      hints={[
        "Run creation should respect role-based write permissions.",
        "Long-running states need clear progress and failure details.",
        "Table and detail views should keep organization filtering strict.",
      ]}
    />
  );
}
