import { FeaturePlaceholder } from "@/components/layout/FeaturePlaceholder";

export default function ChatPage() {
  return (
    <FeaturePlaceholder
      title="Chat"
      summary="Conversational interface for organization-scoped document question answering."
      hints={[
        "Question submission and retrieval options should be permission-aware.",
        "Citations and confidence states should be visible per answer.",
        "Session restoration should avoid cross-organization leakage.",
      ]}
    />
  );
}
