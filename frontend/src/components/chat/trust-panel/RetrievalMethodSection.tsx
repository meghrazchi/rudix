import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { RetrievalMethodRecord } from "@/lib/api/trust_metadata";

export function RetrievalMethodSection({
  retrievalMethod,
}: {
  retrievalMethod: RetrievalMethodRecord | null;
}) {
  if (
    retrievalMethod === null ||
    retrievalMethod.method === "vector" ||
    retrievalMethod.method === "auto_fallback"
  ) {
    return null;
  }

  return (
    <div className="space-y-2">
      <SectionHeader icon="manage_search" label="Search Strategy" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow label="Method" value={retrievalMethod.method_label} />
        {retrievalMethod.override_applied ? (
          <StatRow
            label="Override"
            value={
              retrievalMethod.override_source === "user"
                ? "User-specified"
                : "Admin profile"
            }
          />
        ) : null}
        {!retrievalMethod.override_applied ? (
          <StatRow label="Selection" value="Auto-selected" />
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool Orchestration section (F342)
// ---------------------------------------------------------------------------
