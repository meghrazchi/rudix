import { score } from "@/components/chat/trust-panel/trust-format";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatDebugResponse } from "@/lib/api/chat";

export function VerificationSection({
  debug,
}: {
  debug: ChatDebugResponse | null;
}) {
  return (
    <div className="space-y-2">
      <SectionHeader icon="fact_check" label="Verification" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {debug?.grounded_verification_verdict ? (
          <StatRow
            label="Verdict"
            value={debug.grounded_verification_verdict}
          />
        ) : null}
        {typeof debug?.grounded_verification_score === "number" ? (
          <StatRow
            label="Score"
            value={score(debug.grounded_verification_score)}
          />
        ) : null}
        {(debug?.grounded_verification_claim_count ?? 0) > 0 ? (
          <>
            <StatRow
              label="Claims checked"
              value={debug!.grounded_verification_claim_count}
            />
            <StatRow
              label="Supported"
              value={debug!.grounded_verification_supported_count ?? 0}
            />
            {(debug?.grounded_verification_unsupported_count ?? 0) > 0 ? (
              <StatRow
                label="Unsupported"
                value={debug!.grounded_verification_unsupported_count}
              />
            ) : null}
            {(debug?.grounded_verification_removed_count ?? 0) > 0 ? (
              <StatRow
                label="Removed"
                value={debug!.grounded_verification_removed_count}
              />
            ) : null}
          </>
        ) : null}
        {debug?.grounded_verification_model ? (
          <StatRow
            label="Verifier model"
            value={debug.grounded_verification_model}
            subtle
          />
        ) : null}
      </div>
    </div>
  );
}
