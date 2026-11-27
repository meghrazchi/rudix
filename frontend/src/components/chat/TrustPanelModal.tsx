import { useTranslations } from "next-intl";

import { AnswerTrustPanel } from "@/components/chat/AnswerTrustPanel";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import type { ChatCitationResponse } from "@/lib/api/chat";

/** "Explain answer" dialog that hosts the trust panel. */
export function TrustPanelModal({
  openTrustPanelTurn,
  showDebugDetails,
  session,
  panel,
  feedback,
  overlays,
}: {
  openTrustPanelTurn: ChatTurn;
  showDebugDetails: boolean;
  session: ChatSessionController;
  panel: CitationPanelController;
  feedback: ChatFeedbackController;
  overlays: ChatOverlaysController;
}) {
  const tc = useTranslations("chat.page");
  const { setSelectedResponseMessageId } = session;
  const { setIsKnowledgeHubOpen, setPreviewCitationSet } = panel;
  const {
    chatFeedbackEnabled,
    setTrustPanelFeedbackMessageId,
    setTrustPanelFeedbackContext,
  } = feedback;
  const {
    trustPanelOverlayRef,
    trustPanelModalRef,
    setOpenTrustPanelMessageId,
    setSaveKnowledgeCardMessageId,
  } = overlays;

  return (
    <div
      ref={trustPanelOverlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#171428]/60 p-6 backdrop-blur-[2px] md:p-8"
      onClick={(event) => {
        if (event.target === trustPanelOverlayRef.current) {
          setOpenTrustPanelMessageId(null);
        }
      }}
    >
      <div
        ref={trustPanelModalRef}
        role="dialog"
        aria-modal="true"
        aria-label={tc("answerExplanation")}
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-[#d7d4e8] bg-[#fcf8ff] shadow-[0_30px_90px_rgba(15,10,40,0.35)]"
      >
        <div className="flex items-center justify-between gap-4 border-b border-[#e4e1ee] bg-white px-6 py-4 md:px-8">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#f0ecf9] text-[#3525cd]">
              <span
                className="material-symbols-outlined text-[20px]"
                aria-hidden="true"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                tips_and_updates
              </span>
            </span>
            <p className="text-base font-semibold text-[#1b1b24]">
              Answer Explanation
            </p>
          </div>
          <div className="flex items-center gap-2">
            {openTrustPanelTurn ? (
              <button
                type="button"
                data-testid="trust-panel-save-knowledge-card-btn"
                onClick={() =>
                  setSaveKnowledgeCardMessageId(
                    openTrustPanelTurn.response.message_id,
                  )
                }
                className="inline-flex items-center gap-1 rounded-lg border border-[#d7d4e8] bg-white px-3 py-2 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
                aria-label={tc("saveKnowledgeCard")}
              >
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                >
                  bookmark_add
                </span>
                Save as card
              </button>
            ) : null}
            <button
              type="button"
              data-overlay-autofocus="true"
              aria-label={tc("closeAnswerExplanation")}
              onClick={() => setOpenTrustPanelMessageId(null)}
              className="rounded-lg p-2 text-[#6a6780] transition-colors hover:bg-[#f5f2ff] hover:text-[#2f2a46]"
            >
              <span
                className="material-symbols-outlined text-[20px]"
                aria-hidden="true"
              >
                close
              </span>
            </button>
          </div>
        </div>
        <div className="rudix-chat-scrollbar max-h-[calc(90vh-5.25rem)] overflow-y-auto p-4 md:p-6">
          <AnswerTrustPanel
            messageId={openTrustPanelTurn.response.message_id}
            confidenceScore={openTrustPanelTurn.response.confidence_score}
            confidenceCategory={openTrustPanelTurn.response.confidence_category}
            confidenceExplanation={
              openTrustPanelTurn.response.confidence_explanation
            }
            citationValidationFailed={
              openTrustPanelTurn.response.citation_validation_failed
            }
            verificationFailed={openTrustPanelTurn.response.verification_failed}
            sourceFreshnessWarning={
              openTrustPanelTurn.response.source_freshness_warning
            }
            sourceFreshnessWarningReason={
              openTrustPanelTurn.response.source_freshness_warning_reason
            }
            policyApplied={openTrustPanelTurn.response.policy_applied}
            policyOutcome={openTrustPanelTurn.response.policy_outcome}
            policyViolatedRules={
              openTrustPanelTurn.response.policy_violated_rules
            }
            policyWarningFlags={
              openTrustPanelTurn.response.policy_warning_flags
            }
            policyDisclaimer={openTrustPanelTurn.response.policy_disclaimer}
            citations={openTrustPanelTurn.response.citations}
            debug={openTrustPanelTurn.response.debug}
            trustMetadata={openTrustPanelTurn.response.trust_metadata}
            showInterpretationDetails={showDebugDetails}
            hideHeader
            onOpenCitation={(citation) => {
              const previewCitation = citation as ChatCitationResponse;
              const siblings = openTrustPanelTurn.response.citations.filter(
                (item) => item.document_id === citation.document_id,
              );
              setSelectedResponseMessageId(
                openTrustPanelTurn.response.message_id,
              );
              setOpenTrustPanelMessageId(null);
              setIsKnowledgeHubOpen(false);
              setPreviewCitationSet({
                citations: siblings.length > 0 ? siblings : [previewCitation],
                initialIndex: Math.max(0, siblings.indexOf(previewCitation)),
              });
            }}
            onReportIssue={
              chatFeedbackEnabled
                ? (context) => {
                    setTrustPanelFeedbackMessageId(
                      openTrustPanelTurn.response.message_id,
                    );
                    setTrustPanelFeedbackContext(context);
                  }
                : undefined
            }
            onSaveAsKnowledgeCard={() =>
              setSaveKnowledgeCardMessageId(
                openTrustPanelTurn.response.message_id,
              )
            }
          />
        </div>
      </div>
    </div>
  );
}
