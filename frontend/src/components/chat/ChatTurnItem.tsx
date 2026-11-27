import { useTranslations } from "next-intl";

import { ChatCitationChips } from "@/components/chat/ChatCitationChips";
import { ChatTurnActions } from "@/components/chat/ChatTurnActions";
import { ConflictWarningCard } from "@/components/chat/ConflictIndicators";
import { agentRunStatusClass } from "@/components/chat/chat-session-utils";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import { SuggestedKnowledgeCard } from "@/components/verified-answers/SuggestedKnowledgeCard";

export function ChatTurnItem({
  turn,
  isLatestTurn,
  selectedCollectionIds,
  regenerateDisabled,
  onRegenerate,
  session,
  panel,
  feedback,
  overlays,
}: {
  turn: ChatTurn;
  isLatestTurn: boolean;
  selectedCollectionIds: string[];
  regenerateDisabled: boolean;
  onRegenerate: (question: string) => void;
  session: ChatSessionController;
  panel: CitationPanelController;
  feedback: ChatFeedbackController;
  overlays: ChatOverlaysController;
}) {
  const tc = useTranslations("chat.page");
  const { setSelectedResponseMessageId } = session;
  const { setIsKnowledgeHubOpen } = panel;

  return (
    <li key={turn.response.message_id} className="space-y-3">
      <div className="flex flex-col items-end gap-2">
        <article className="max-w-[85%] rounded-3xl rounded-tr-none bg-[#f0ecf9] px-6 py-4 shadow-sm">
          <p className="sr-only">{tc("questionLabel")}</p>
          <p className="rudix-chat-scrollbar max-h-72 overflow-y-auto pr-1 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-[#1b1b24]">
            {turn.question}
          </p>
        </article>
        <div className="mr-2 flex items-center gap-2 text-[10px] font-bold tracking-widest text-[#777587] uppercase">
          <span>{tc("you")}</span>
        </div>
      </div>

      <div className="flex flex-col items-start gap-3">
        <div className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#3525cd] text-white">
          <span
            className="material-symbols-outlined text-[18px]"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            auto_awesome
          </span>
        </div>
        <div className="flex w-full min-w-0 flex-1 flex-col">
          <article className="rounded-3xl rounded-tl-none border border-[#e4e1ee] bg-white px-6 py-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-[#3525cd] text-[10px] font-bold text-white italic">
                R
              </span>
              <span className="text-[10px] font-bold tracking-widest text-[#3525cd] uppercase">
                Rudix AI
              </span>
            </div>

            {turn.response.trust_metadata?.query_interpretation?.answer_mode ===
              "guidance" ||
            turn.response.scope_label ||
            turn.response.agent_run_status ? (
              <div className="mb-4 flex flex-wrap items-center gap-2">
                {turn.response.trust_metadata?.query_interpretation
                  ?.answer_mode === "guidance" ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-800">
                    <span
                      className="material-symbols-outlined text-[11px]"
                      aria-hidden="true"
                    >
                      tips_and_updates
                    </span>
                    General product guidance
                  </span>
                ) : null}
                {turn.response.scope_label ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2 py-0.5 text-[10px] font-semibold text-[#3525cd]">
                    <span
                      className="material-symbols-outlined text-[11px]"
                      aria-hidden="true"
                    >
                      filter_alt
                    </span>
                    {turn.response.scope_label}
                  </span>
                ) : null}
                {turn.response.agent_run_status ? (
                  <span
                    className={agentRunStatusClass(
                      turn.response.agent_run_status,
                    )}
                  >
                    {tc("agentStatus", {
                      status: turn.response.agent_run_status,
                    })}
                  </span>
                ) : null}
              </div>
            ) : null}

            {turn.response.citation_validation_failed &&
            !turn.response.not_found ? (
              <p className="mb-3 rounded-lg border border-[#f5c6b0] bg-[#fff8f5] px-3 py-2 text-xs text-[#7a3a20]">
                {tc("citationValidationFailed")}
              </p>
            ) : null}

            <ConflictWarningCard
              conflictDetected={turn.response.conflict_detected}
              agreementLevel={turn.response.agreement_level}
              conflictSummary={turn.response.conflict_summary}
              preferredDocumentIds={turn.response.preferred_document_ids}
            />

            {turn.response.citations.some(
              (citation) =>
                citation.doc_stale_warning ||
                citation.doc_expired_warning ||
                citation.doc_is_excluded_status,
            ) ? (
              <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Some citations come from stale, expired, or archived sources.
              </p>
            ) : null}

            {!turn.response.not_found && (
              <SuggestedKnowledgeCard
                query={turn.question}
                collectionId={selectedCollectionIds[0] ?? null}
              />
            )}
            {turn.response.not_found ? (
              <div className="space-y-2">
                <p className="rounded-lg border border-[#d2cee6] bg-[#faf9ff] px-3 py-2 text-[15px] break-words text-[#2f2a46]">
                  {tc("notFoundAnswer")}
                </p>
                <p className="text-xs text-[#6a6780]">{tc("notFoundHint")}</p>
              </div>
            ) : (
              <>
                <p className="rudix-chat-scrollbar max-h-80 overflow-y-auto pr-1 text-[16px] leading-relaxed break-words whitespace-pre-wrap text-[#2f2a46]">
                  {turn.response.answer}
                </p>
                <ChatCitationChips
                  turn={turn}
                  session={session}
                  panel={panel}
                />
                {turn.response.citations[0]?.text_snippet && (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedResponseMessageId(turn.response.message_id);
                      setIsKnowledgeHubOpen(true);
                    }}
                    className="mt-4 w-full cursor-pointer rounded-3xl border border-[#e4e1ee] bg-white px-5 py-4 text-left text-sm leading-relaxed text-[#464555] italic shadow-sm transition-colors hover:border-[#c3c0ff] hover:bg-[#f5f2ff]"
                  >
                    {turn.response.citations[0].text_snippet}
                  </button>
                )}
              </>
            )}
            {turn.response.agent_run_error ? (
              <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                {tc("agentStopReason", {
                  reason: turn.response.agent_run_error.message,
                })}
              </p>
            ) : null}
          </article>
          <ChatTurnActions
            turn={turn}
            isLatestTurn={isLatestTurn}
            regenerateDisabled={regenerateDisabled}
            onRegenerate={onRegenerate}
            session={session}
            feedback={feedback}
            overlays={overlays}
          />
        </div>
      </div>
    </li>
  );
}
