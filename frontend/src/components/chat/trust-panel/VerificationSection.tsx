import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat.trustPanel");
  return (
    <div className="space-y-2">
      <SectionHeader icon="fact_check" label={t("verification.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {debug?.grounded_verification_verdict ? (
          <StatRow
            label={t("verification.verdict")}
            value={debug.grounded_verification_verdict}
          />
        ) : null}
        {typeof debug?.grounded_verification_score === "number" ? (
          <StatRow
            label={t("verification.score")}
            value={score(debug.grounded_verification_score)}
          />
        ) : null}
        {(debug?.grounded_verification_claim_count ?? 0) > 0 ? (
          <>
            <StatRow
              label={t("verification.claimsChecked")}
              value={debug!.grounded_verification_claim_count}
            />
            <StatRow
              label={t("verification.supported")}
              value={debug!.grounded_verification_supported_count ?? 0}
            />
            {(debug?.grounded_verification_unsupported_count ?? 0) > 0 ? (
              <StatRow
                label={t("verification.unsupported")}
                value={debug!.grounded_verification_unsupported_count}
              />
            ) : null}
            {(debug?.grounded_verification_removed_count ?? 0) > 0 ? (
              <StatRow
                label={t("verification.removed")}
                value={debug!.grounded_verification_removed_count}
              />
            ) : null}
          </>
        ) : null}
        {debug?.grounded_verification_model ? (
          <StatRow
            label={t("verification.verifierModel")}
            value={debug.grounded_verification_model}
            subtle
          />
        ) : null}
      </div>
    </div>
  );
}
