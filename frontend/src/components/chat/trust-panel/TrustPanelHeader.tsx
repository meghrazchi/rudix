import { answerModeBadge } from "@/components/chat/trust-panel/trust-badges";
import type { TrustPanelProps } from "@/components/chat/AnswerTrustPanel";
import { trackFeatureEvent } from "@/lib/analytics";
import type { ChatDebugResponse } from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

type DiagnosticsMode = "basic" | "expert";

export function TrustPanelHeader({
  messageId,
  hideHeader,
  showInterpretationDetails,
  diagnosticsMode,
  setDiagnosticsMode,
  answerModeBadgeRecord,
  warnings,
  confidenceScore,
  trustMetadata,
  debug,
  onSaveAsKnowledgeCard,
  onReportIssue,
}: {
  messageId: string;
  hideHeader: boolean;
  showInterpretationDetails: boolean;
  diagnosticsMode: DiagnosticsMode;
  setDiagnosticsMode: (mode: DiagnosticsMode) => void;
  answerModeBadgeRecord: ReturnType<typeof answerModeBadge>;
  warnings: string[];
  confidenceScore: number;
  trustMetadata: AnswerTrustMetadataResponse | null | undefined;
  debug: ChatDebugResponse | null;
  onSaveAsKnowledgeCard: TrustPanelProps["onSaveAsKnowledgeCard"];
  onReportIssue: TrustPanelProps["onReportIssue"];
}) {
  return (
    <>
      {hideHeader ? (
        <div className="flex justify-center px-4 pt-4 md:px-6 md:pt-5">
          {showInterpretationDetails ? (
            <div
              className="inline-flex rounded-full border border-[#d7d4e8] bg-white p-0.5 text-[10px] font-semibold shadow-sm"
              role="tablist"
              aria-label="Retrieval diagnostics mode"
            >
              <button
                type="button"
                role="tab"
                aria-selected={diagnosticsMode === "basic"}
                onClick={() => setDiagnosticsMode("basic")}
                className={`rounded-full px-3.5 py-1.5 transition-colors ${
                  diagnosticsMode === "basic"
                    ? "bg-[#3525cd] text-white"
                    : "text-[#6a6780] hover:text-[#3525cd]"
                }`}
              >
                Basic
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={diagnosticsMode === "expert"}
                onClick={() => setDiagnosticsMode("expert")}
                className={`rounded-full px-3.5 py-1.5 transition-colors ${
                  diagnosticsMode === "expert"
                    ? "bg-[#3525cd] text-white"
                    : "text-[#6a6780] hover:text-[#3525cd]"
                }`}
              >
                Expert
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex items-start justify-between gap-4 border-b border-[#e4e1ee] bg-white px-4 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#3525cd] text-white shadow-sm">
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  check_circle
                </span>
              </span>
              <div className="min-w-0">
                <p className="text-[10px] font-bold tracking-[0.18em] text-[#777587] uppercase">
                  Answer Explanation
                </p>
                <p className="truncate text-sm font-semibold text-[#1b1b24]">
                  Model view
                </p>
              </div>
            </div>
            <p className="mt-2 max-w-2xl text-xs leading-relaxed text-[#6a6780]">
              Confidence, source selection, and citation support are grouped
              into a single review panel.
            </p>
            {answerModeBadgeRecord ? (
              <div className="mt-2">
                <span className={`${answerModeBadgeRecord.cls} inline-flex`}>
                  <span
                    className="material-symbols-outlined text-[10px]"
                    aria-hidden="true"
                  >
                    {answerModeBadgeRecord.icon}
                  </span>
                  {answerModeBadgeRecord.label}
                </span>
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            {onSaveAsKnowledgeCard ? (
              <button
                type="button"
                data-testid="trust-panel-save-knowledge-card-btn"
                onClick={onSaveAsKnowledgeCard}
                className="flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] font-medium text-indigo-700 hover:bg-indigo-100 focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:outline-none"
                aria-label="Save as knowledge card"
              >
                <span
                  className="material-symbols-outlined text-[12px]"
                  aria-hidden="true"
                >
                  bookmark_add
                </span>
                Save as card
              </button>
            ) : null}
            {showInterpretationDetails ? (
              <div
                className="inline-flex rounded-full border border-[#d7d4e8] bg-white p-0.5 text-[10px] font-semibold"
                role="tablist"
                aria-label="Retrieval diagnostics mode"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={diagnosticsMode === "basic"}
                  onClick={() => setDiagnosticsMode("basic")}
                  className={`rounded-full px-2.5 py-1 transition-colors ${
                    diagnosticsMode === "basic"
                      ? "bg-[#3525cd] text-white"
                      : "text-[#6a6780] hover:text-[#3525cd]"
                  }`}
                >
                  Basic
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={diagnosticsMode === "expert"}
                  onClick={() => setDiagnosticsMode("expert")}
                  className={`rounded-full px-2.5 py-1 transition-colors ${
                    diagnosticsMode === "expert"
                      ? "bg-[#3525cd] text-white"
                      : "text-[#6a6780] hover:text-[#3525cd]"
                  }`}
                >
                  Expert
                </button>
              </div>
            ) : null}
            {onReportIssue ? (
              <button
                type="button"
                data-testid="trust-panel-report-issue-btn"
                onClick={() => {
                  void trackFeatureEvent(
                    "feature.chat.trust_panel_feedback_submitted",
                    {
                      surface: "app",
                      route: "/chat",
                      pageKey: "chat",
                      featureArea: "chat",
                      entityId: messageId,
                      count: warnings.length,
                    },
                  );
                  onReportIssue({
                    warnings,
                    traceId:
                      trustMetadata?.retrieval.trace_request_id ??
                      debug?.trace_request_id ??
                      null,
                    trustScore: confidenceScore,
                    trustLevel: trustMetadata?.confidence.trust_level ?? null,
                  });
                }}
                className="flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-2 py-1 text-[10px] font-medium text-rose-700 hover:bg-rose-100 focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:outline-none"
                aria-label="Report an issue with this answer"
              >
                <span
                  className="material-symbols-outlined text-[12px]"
                  aria-hidden="true"
                >
                  flag
                </span>
                Report issue
              </button>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}
