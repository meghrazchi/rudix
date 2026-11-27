import Link from "next/link";
import { useTranslations } from "next-intl";

import { CitationDetails } from "@/components/chat/CitationDetails";
import { KnowledgeHub } from "@/components/chat/KnowledgeHub";
import { toAbsoluteBrowserHref } from "@/components/chat/chat-citations";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { AgentRunTimelineController } from "@/components/chat/hooks/useAgentRunTimeline";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import { getApiErrorMessage } from "@/lib/api/errors";
import { copyToClipboard } from "@/lib/export-utils";

/** Right-hand panel: citation details or the knowledge hub. */
export function EvidenceAside({
  panel,
  agentRun,
  selectedCitationTurn,
  canDecideApprovals,
  showDebugDetails,
}: {
  panel: CitationPanelController;
  agentRun: AgentRunTimelineController;
  selectedCitationTurn: ChatTurn | null;
  canDecideApprovals: boolean;
  showDebugDetails: boolean;
}) {
  const tc = useTranslations("chat.page");
  const {
    isKnowledgeHubOpen,
    previewCitationSet,
    setIsKnowledgeHubOpen,
    setPreviewCitationSet,
    copiedCitationLinkKey,
    setCopiedCitationLinkKey,
    citationDownloadMutation,
    selectedCitationDocumentCount,
    activePreviewCitation,
    activePreviewCitationSourceHref,
    isActivePreviewCitationSourceExternal,
    activePreviewCitationKey,
  } = panel;

  return (
    <aside
      className={`relative flex min-h-0 flex-col overflow-hidden border-l border-[#e4e1ee] bg-[#fcf8ff] shadow-sm ${isKnowledgeHubOpen || previewCitationSet !== null ? "" : "hidden"}`}
    >
      <div className="flex min-h-16 shrink-0 items-center justify-between border-b border-[#e4e1ee] bg-white px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="h-2.5 w-2.5 rounded-full bg-[#3525cd] shadow-[0_0_8px_rgba(53,37,205,0.6)]" />
          <div>
            <h2 className="font-bold tracking-tight text-[#1b1b24]">
              {activePreviewCitation
                ? tc("citationDetailsTitle")
                : tc("knowledgeHubTitle")}
            </h2>
            <p className="text-xs text-[#464555]">
              {activePreviewCitation
                ? tc("citationDetailsSubtitle")
                : tc("knowledgeHubSubtitle")}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setIsKnowledgeHubOpen(false);
            setPreviewCitationSet(null);
          }}
          aria-label={
            activePreviewCitation
              ? tc("closeCitationDetails")
              : tc("closeKnowledgeHub")
          }
          className="cursor-pointer rounded-full p-2 text-[#777587] transition-colors hover:bg-[#f0ecf9] hover:text-[#1b1b24]"
        >
          <span
            className="material-symbols-outlined text-[20px]"
            aria-hidden="true"
          >
            close
          </span>
        </button>
      </div>

      <div className="rudix-chat-scrollbar flex-1 overflow-y-auto">
        {activePreviewCitation ? (
          <CitationDetails
            panel={panel}
            activePreviewCitation={activePreviewCitation}
          />
        ) : (
          <KnowledgeHub
            panel={panel}
            agentRun={agentRun}
            selectedCitationTurn={selectedCitationTurn}
            canDecideApprovals={canDecideApprovals}
            showDebugDetails={showDebugDetails}
          />
        )}
      </div>

      {activePreviewCitation ? (
        <div className="border-t border-[#e4e1ee] bg-[#f5f2ff] p-4">
          <div className="mb-4 grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => {
                if (
                  !activePreviewCitationSourceHref ||
                  !activePreviewCitationKey
                ) {
                  return;
                }
                void copyToClipboard(
                  toAbsoluteBrowserHref(activePreviewCitationSourceHref),
                ).then(() => {
                  setCopiedCitationLinkKey(activePreviewCitationKey);
                  window.setTimeout(() => setCopiedCitationLinkKey(null), 1800);
                });
              }}
              className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-[#c7c4d8] bg-white px-2 py-2.5 text-[11px] font-black text-[#464555] shadow-sm transition-colors hover:bg-[#f0ecf9] hover:text-[#3525cd]"
            >
              <span
                className="material-symbols-outlined text-[18px]"
                aria-hidden="true"
              >
                link
              </span>
              {copiedCitationLinkKey === activePreviewCitationKey
                ? tc("citationCopiedLink")
                : tc("citationCopyLink")}
            </button>

            {isActivePreviewCitationSourceExternal ? (
              <a
                href={activePreviewCitationSourceHref ?? "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col items-center justify-center gap-1 rounded-xl border border-[#c7c4d8] bg-white px-2 py-2.5 text-[11px] font-black text-[#464555] shadow-sm transition-colors hover:bg-[#f0ecf9] hover:text-[#3525cd]"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  open_in_new
                </span>
                {tc("citationOpenSource")}
              </a>
            ) : (
              <Link
                href={activePreviewCitationSourceHref ?? "#"}
                className="flex flex-col items-center justify-center gap-1 rounded-xl border border-[#c7c4d8] bg-white px-2 py-2.5 text-[11px] font-black text-[#464555] shadow-sm transition-colors hover:bg-[#f0ecf9] hover:text-[#3525cd]"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  open_in_new
                </span>
                {tc("citationOpenSource")}
              </Link>
            )}

            <button
              type="button"
              disabled={citationDownloadMutation.isPending}
              onClick={() => {
                citationDownloadMutation.mutate(activePreviewCitation);
              }}
              className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-[#c7c4d8] bg-white px-2 py-2.5 text-[11px] font-black text-[#464555] shadow-sm transition-colors hover:bg-[#f0ecf9] hover:text-[#3525cd] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span
                className="material-symbols-outlined text-[18px]"
                aria-hidden="true"
              >
                download
              </span>
              {citationDownloadMutation.isPending
                ? tc("citationDownloading")
                : tc("citationDownload")}
            </button>
          </div>
          {citationDownloadMutation.isError ? (
            <p className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {getApiErrorMessage(citationDownloadMutation.error)}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setPreviewCitationSet(null);
              setIsKnowledgeHubOpen(true);
            }}
            className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-2xl bg-[#3525cd] px-4 py-3 text-sm font-black text-white shadow-sm transition-colors hover:bg-[#2b1fa6]"
          >
            <span
              className="material-symbols-outlined text-[18px]"
              aria-hidden="true"
            >
              insights
            </span>
            {tc("citationReadCollectionInsights")}
          </button>
        </div>
      ) : (
        <div className="border-t border-[#e4e1ee] bg-white p-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-[#c7c4d8] bg-[#f0ecf9] p-2">
              <p className="mb-1 text-[9px] font-bold tracking-wider text-[#464555] uppercase">
                {tc("confidenceMetric")}
              </p>
              <p className="text-lg font-semibold text-[#3525cd]">
                {selectedCitationTurn
                  ? selectedCitationTurn.response.confidence_category === "high"
                    ? tc("confidenceHigh")
                    : selectedCitationTurn.response.confidence_category ===
                        "medium"
                      ? tc("confidenceMedium")
                      : tc("confidenceLow")
                  : "—"}
              </p>
            </div>
            <div className="rounded-lg border border-[#c7c4d8] bg-[#f0ecf9] p-2">
              <p className="mb-1 text-[9px] font-bold tracking-wider text-[#464555] uppercase">
                {tc("sourcesMetric")}
              </p>
              <p className="text-lg font-semibold text-[#3525cd]">
                {selectedCitationDocumentCount > 0
                  ? String(selectedCitationDocumentCount).padStart(2, "0")
                  : "—"}
              </p>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
