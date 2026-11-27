import { useTranslations } from "next-intl";

import type { ChatTurn } from "@/components/chat/chat-types";

/** Fallback warning (all users) and retrieval debug details (admins). */
export function RetrievalDebug({
  selectedCitationTurn,
  showDebugDetails,
}: {
  selectedCitationTurn: ChatTurn | null;
  showDebugDetails: boolean;
}) {
  const tc = useTranslations("chat.page");

  return (
    <>
      {/* Fallback warning — visible to all users */}
      {selectedCitationTurn?.response.debug?.fallback_used ? (
        <div className="mt-3 flex items-start gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span className="mt-0.5 shrink-0">⚠</span>
          <span>
            {selectedCitationTurn.response.debug.fallback_to
              ? tc("fallbackWarningWithProvider", {
                  provider: selectedCitationTurn.response.debug.fallback_to,
                })
              : tc("fallbackWarning")}
          </span>
        </div>
      ) : null}

      {/* Debug details for admins */}
      {showDebugDetails && selectedCitationTurn?.response.debug ? (
        <details className="mt-4">
          <summary className="cursor-pointer text-[10px] font-bold tracking-widest text-[#464555] uppercase">
            {tc("retrievalDebug")}
          </summary>
          <div className="mt-2 space-y-1 text-xs text-[#4f4b63]">
            <dl className="grid grid-cols-2 gap-1 rounded border border-[#ebe8f7] px-2 py-2">
              {(
                [
                  "retrieval_count",
                  "selected_count",
                  "rerank_applied",
                  "embedding_model",
                  "llm_model",
                  "llm_provider",
                  "fallback_used",
                  "fallback_from",
                  "fallback_to",
                  "graph_context_enabled",
                  "graph_context_used",
                  "graph_context_unavailable",
                  "graph_context_reason",
                  "graph_seed_entity_count",
                  "graph_related_entity_count",
                  "graph_chunk_count",
                  "graph_max_hops_used",
                  "graph_relation_types_used",
                  "detected_language",
                  "answer_language_used",
                ] as const
              ).map((key) => (
                <div
                  key={key}
                  className={
                    key === "llm_model" ||
                    key === "llm_provider" ||
                    key === "graph_context_reason" ||
                    key === "graph_relation_types_used"
                      ? "col-span-2"
                      : ""
                  }
                >
                  <dt className="font-semibold">{key}</dt>
                  <dd>
                    {String(
                      (
                        selectedCitationTurn.response.debug as Record<
                          string,
                          unknown
                        >
                      )[key] ?? "N/A",
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </details>
      ) : null}
    </>
  );
}
