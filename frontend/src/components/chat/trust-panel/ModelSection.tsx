import { useTranslations } from "next-intl";

import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatDebugResponse } from "@/lib/api/chat";

export function ModelSection({ debug }: { debug: ChatDebugResponse }) {
  const t = useTranslations("chat.trustPanel");
  return (
    <div className="space-y-2">
      <SectionHeader icon="model_training" label={t("model.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow
          label={t("model.provider")}
          value={debug.llm_provider ?? null}
        />
        <StatRow label={t("model.llmModel")} value={debug.llm_model ?? null} />
        <StatRow
          label={t("model.embeddings")}
          value={debug.embedding_model ?? null}
        />
        {debug.prompt_template_key ? (
          <StatRow
            label={t("model.promptTemplate")}
            value={
              debug.prompt_template_version
                ? `${debug.prompt_template_key} v${debug.prompt_template_version}`
                : debug.prompt_template_key
            }
          />
        ) : null}
        {debug.fallback_used ? (
          <>
            <StatRow
              label={t("model.fallbackFrom")}
              value={debug.fallback_from ?? t("model.fallbackPrimary")}
            />
            <StatRow
              label={t("model.fallbackTo")}
              value={debug.fallback_to ?? null}
            />
            {debug.fallback_reason ? (
              <StatRow
                label={t("model.fallbackReason")}
                value={debug.fallback_reason}
              />
            ) : null}
          </>
        ) : null}
        {debug.detected_language ? (
          <StatRow
            label={t("model.detectedLanguage")}
            value={debug.detected_language}
          />
        ) : null}
        {debug.answer_language_used ? (
          <StatRow
            label={t("model.answerLanguage")}
            value={debug.answer_language_used}
          />
        ) : null}
      </div>
    </div>
  );
}
