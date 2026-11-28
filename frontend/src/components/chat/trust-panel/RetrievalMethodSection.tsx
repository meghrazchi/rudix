import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat.trustPanel");
  if (
    retrievalMethod === null ||
    retrievalMethod.method === "vector" ||
    retrievalMethod.method === "auto_fallback"
  ) {
    return null;
  }

  return (
    <div className="space-y-2">
      <SectionHeader icon="manage_search" label={t("method.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow
          label={t("method.method")}
          value={retrievalMethod.method_label}
        />
        {retrievalMethod.override_applied ? (
          <StatRow
            label={t("method.override")}
            value={
              retrievalMethod.override_source === "user"
                ? t("method.overrideUser")
                : t("method.overrideAdmin")
            }
          />
        ) : null}
        {!retrievalMethod.override_applied ? (
          <StatRow label={t("method.selection")} value={t("method.auto")} />
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool Orchestration section (F342)
// ---------------------------------------------------------------------------
