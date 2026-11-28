import { useTranslations } from "next-intl";

import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";

export function PolicySection({
  policyOutcome,
  policyViolatedRules,
  policyWarningFlags,
}: {
  policyOutcome: string | null;
  policyViolatedRules: string[];
  policyWarningFlags: string[];
}) {
  const t = useTranslations("chat.trustPanel");
  return (
    <div className="space-y-2">
      <SectionHeader icon="policy" label={t("policy.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {policyOutcome ? (
          <StatRow label={t("policy.outcome")} value={policyOutcome} />
        ) : null}
        {policyViolatedRules.length > 0 ? (
          <StatRow
            label={t("policy.violated")}
            value={policyViolatedRules.join(", ")}
          />
        ) : null}
        {policyWarningFlags.length > 0 ? (
          <StatRow
            label={t("policy.warnings")}
            value={policyWarningFlags.join(", ")}
          />
        ) : null}
      </div>
    </div>
  );
}
