import { memo } from "react";

import { useTranslations } from "next-intl";

import { ChatCitationChips } from "@/components/chat/ChatCitationChips";
import {
  ChatTurnActions,
  type ChatTurnView,
} from "@/components/chat/ChatTurnActions";
import { ConflictWarningCard } from "@/components/chat/ConflictIndicators";
import { agentRunStatusClass } from "@/components/chat/chat-session-utils";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatTurnHandlers } from "@/components/chat/hooks/useChatTurnHandlers";
import { SuggestedKnowledgeCard } from "@/components/verified-answers/SuggestedKnowledgeCard";

export type ChatTurnItemProps = ChatTurnView & {
  turn: ChatTurn;
  /** First selected collection, for knowledge-card suggestions. */
  collectionId: string | null;
  /** Stable for the life of the thread (useChatTurnHandlers). */
  handlers: ChatTurnHandlers;
  /** Position in the thread; set as data-index for the virtualiser. */
  index?: number;
  /** Virtualiser measuring ref (stable), so rows can have dynamic heights. */
  measureRef?: (element: Element | null) => void;
};

/**
 * One completed question/answer turn. Memoised (R05-11): every prop is a
 * primitive, the immutable turn object, or the stable handlers object, so a
 * streaming token or an unrelated page update never re-renders it.
 */
export const ChatTurnItem = memo(function ChatTurnItem({
  turn,
  collectionId,
  handlers,
  index,
  measureRef,
  ...view
}: ChatTurnItemProps) {
  const tc = useTranslations("chat.page");
  const tt = useTranslations("chat.trustPanel");

  return (
    <li
      ref={measureRef}
      data-index={index}
      data-chat-turn={turn.response.message_id}
      className="space-y-3"
    >
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
                {tc("assistantName")}
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
                    {tt("badge.guidance")}
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
                {tc("staleCitationsNotice")}
              </p>
            ) : null}

            {!turn.response.not_found && (
              <SuggestedKnowledgeCard
                query={turn.question}
                collectionId={collectionId}
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
                <ChatCitationChips turn={turn} handlers={handlers} />
                {turn.response.citations[0]?.text_snippet && (
                  <button
                    type="button"
                    onClick={() => {
                      handlers.openKnowledgeHub(turn.response.message_id);
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
          <ChatTurnActions turn={turn} view={view} handlers={handlers} />
        </div>
      </div>
    </li>
  );
});
