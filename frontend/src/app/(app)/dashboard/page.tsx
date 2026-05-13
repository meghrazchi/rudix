import { FeaturePlaceholder } from "@/components/layout/FeaturePlaceholder";

export default function DashboardPage() {
  return (
    <FeaturePlaceholder
      title="Dashboard"
      summary="Organization-level health and usage overview for documents, pipeline outcomes, and question-answering quality."
      hints={[
        "Permission-aware summaries should stay organization scoped.",
        "Loading, empty, and error states should be explicit per widget.",
        "High-level KPIs should remain actionable without exposing sensitive content.",
      ]}
    />
  );
}
