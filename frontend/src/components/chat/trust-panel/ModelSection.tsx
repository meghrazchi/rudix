import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatDebugResponse } from "@/lib/api/chat";

export function ModelSection({ debug }: { debug: ChatDebugResponse }) {
  return (
    <div className="space-y-2">
      <SectionHeader icon="model_training" label="Model" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow label="Provider" value={debug.llm_provider ?? null} />
        <StatRow label="LLM model" value={debug.llm_model ?? null} />
        <StatRow label="Embeddings" value={debug.embedding_model ?? null} />
        {debug.prompt_template_key ? (
          <StatRow
            label="Prompt template"
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
              label="Fallback from"
              value={debug.fallback_from ?? "primary"}
            />
            <StatRow label="Fallback to" value={debug.fallback_to ?? null} />
            {debug.fallback_reason ? (
              <StatRow label="Fallback reason" value={debug.fallback_reason} />
            ) : null}
          </>
        ) : null}
        {debug.detected_language ? (
          <StatRow label="Detected language" value={debug.detected_language} />
        ) : null}
        {debug.answer_language_used ? (
          <StatRow label="Answer language" value={debug.answer_language_used} />
        ) : null}
      </div>
    </div>
  );
}
