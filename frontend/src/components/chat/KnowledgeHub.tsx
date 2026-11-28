import Link from "next/link";
import { useTranslations } from "next-intl";

import { AgentRunTimeline } from "@/components/chat/AgentRunTimeline";
import { RetrievalDebug } from "@/components/chat/RetrievalDebug";
import {
  agreementLevelClass,
  agreementLevelLabel,
} from "@/components/chat/ConflictIndicators";
import { buildChatPipelineHref } from "@/components/chat/chat-session-utils";
import {
  formatScore,
  getFileTypeColorClass,
  getFileTypeLabel,
} from "@/components/chat/chat-format";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { AgentRunTimelineController } from "@/components/chat/hooks/useAgentRunTimeline";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";

export function KnowledgeHub({
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
  const tt = useTranslations("chat.trustPanel");
  const { setPreviewCitationSet, setIsKnowledgeHubOpen } = panel;
  const selectedCitationPipelineHref = selectedCitationTurn
    ? buildChatPipelineHref(selectedCitationTurn.response)
    : null;

  return (
    <>
      {/* Context Map */}
      <div className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
            {tc("contextMapTitle")}
          </span>
          <button
            type="button"
            className="text-[10px] font-bold text-[#3525cd]"
          >
            {tc("contextMapExpand")}
          </button>
        </div>
        <div className="group relative h-40 overflow-hidden rounded-xl border border-[#c7c4d8] bg-[#f0ecf9]">
          <div className="pointer-events-none absolute inset-0 opacity-20">
            <svg className="h-full w-full">
              <line
                stroke="#3525cd"
                strokeWidth="1"
                x1="20%"
                y1="30%"
                x2="50%"
                y2="50%"
              />
              <line
                stroke="#3525cd"
                strokeWidth="1"
                x1="50%"
                y1="50%"
                x2="80%"
                y2="20%"
              />
              <line
                stroke="#3525cd"
                strokeWidth="1"
                x1="50%"
                y1="50%"
                x2="70%"
                y2="80%"
              />
            </svg>
          </div>
          <div className="absolute top-[30%] left-[20%] h-3 w-3 rounded-full bg-[#3525cd] shadow-lg" />
          <div className="absolute top-[50%] left-[50%] flex h-6 w-6 items-center justify-center rounded-full bg-[#3525cd] shadow-lg">
            <span
              className="material-symbols-outlined text-xs text-white"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              stars
            </span>
          </div>
          <div className="absolute top-[20%] left-[78%] h-2.5 w-2.5 rounded-full bg-[#505f76] shadow-lg" />
          <div className="absolute top-[78%] left-[68%] h-4 w-4 rounded-full bg-[#a44100] shadow-lg" />
          <div className="absolute right-2 bottom-2 left-2 rounded border border-[#c7c4d8] bg-white/80 px-2 py-0.5 text-center font-mono text-[9px] text-[#464555] backdrop-blur-sm">
            {tc("contextMapConnected", {
              count: selectedCitationTurn?.response.citations.length ?? 0,
            })}
          </div>
        </div>
      </div>

      {/* Source Documents */}
      <div className="border-t border-[#e4e1ee] bg-[#f5f2ff] p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
            {tc("sourceDocsTitle")}
          </span>
          <span
            className="material-symbols-outlined text-sm text-[#464555]"
            aria-hidden="true"
          >
            filter_list
          </span>
        </div>

        {!selectedCitationTurn ? (
          <p className="text-xs text-[#777587]">{tc("sourceDocsAsk")}</p>
        ) : selectedCitationTurn.response.conflict_detected ? (
          <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={agreementLevelClass(
                  selectedCitationTurn.response.agreement_level,
                )}
              >
                {agreementLevelLabel(
                  selectedCitationTurn.response.agreement_level,
                  tt,
                )}
              </span>
              <span className="font-semibold">{tt("conflict.comparison")}</span>
            </div>
            {selectedCitationTurn.response.conflict_summary ? (
              <p className="mt-1 text-[11px] leading-snug">
                {selectedCitationTurn.response.conflict_summary}
              </p>
            ) : null}
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-2 text-[10px] font-bold tracking-widest text-emerald-800 uppercase">
                  {tt("conflict.preferredSources")}
                </p>
                <div className="space-y-2">
                  {selectedCitationTurn.response.citations
                    .filter((citation) =>
                      selectedCitationTurn.response.preferred_document_ids.includes(
                        citation.document_id,
                      ),
                    )
                    .map((citation, ci) => (
                      <button
                        key={`preferred:${citation.document_id}:${citation.chunk_id}:${ci}`}
                        type="button"
                        onClick={() => {
                          const siblings =
                            selectedCitationTurn.response.citations.filter(
                              (c) => c.document_id === citation.document_id,
                            );
                          setPreviewCitationSet({
                            citations:
                              siblings.length > 0 ? siblings : [citation],
                            initialIndex: Math.max(
                              0,
                              siblings.indexOf(citation),
                            ),
                          });
                          setIsKnowledgeHubOpen(false);
                        }}
                        className="group w-full rounded-lg border border-emerald-200 bg-white p-3 text-left transition-all hover:border-emerald-400"
                      >
                        <div className="mb-1 flex items-center justify-between">
                          <span
                            className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                          >
                            {getFileTypeLabel(citation.filename)}
                          </span>
                          <span className="text-[9px] font-semibold text-emerald-700 uppercase">
                            {tt("badge.preferred")}
                          </span>
                        </div>
                        <h4
                          className="truncate text-sm font-bold text-[#1b1b24]"
                          title={citation.filename ?? tc("unknownDocument")}
                        >
                          {citation.filename ?? tc("unknownDocument")}
                        </h4>
                        {citation.page_number ? (
                          <p className="text-[9px] text-[#464555]">
                            {tc("citationPositionPage", {
                              page: citation.page_number,
                            })}
                          </p>
                        ) : null}
                      </button>
                    ))}
                </div>
              </div>
              <div>
                <p className="mb-2 text-[10px] font-bold tracking-widest text-rose-800 uppercase">
                  {tt("conflict.conflictingSources")}
                </p>
                <div className="space-y-2">
                  {selectedCitationTurn.response.citations
                    .filter((citation) =>
                      selectedCitationTurn.response.conflicting_document_ids.includes(
                        citation.document_id,
                      ),
                    )
                    .map((citation, ci) => (
                      <button
                        key={`conflicting:${citation.document_id}:${citation.chunk_id}:${ci}`}
                        type="button"
                        onClick={() => {
                          const siblings =
                            selectedCitationTurn.response.citations.filter(
                              (c) => c.document_id === citation.document_id,
                            );
                          setPreviewCitationSet({
                            citations:
                              siblings.length > 0 ? siblings : [citation],
                            initialIndex: Math.max(
                              0,
                              siblings.indexOf(citation),
                            ),
                          });
                          setIsKnowledgeHubOpen(false);
                        }}
                        className="group w-full rounded-lg border border-rose-200 bg-white p-3 text-left transition-all hover:border-rose-400"
                      >
                        <div className="mb-1 flex items-center justify-between">
                          <span
                            className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                          >
                            {getFileTypeLabel(citation.filename)}
                          </span>
                          <span className="text-[9px] font-semibold text-rose-700 uppercase">
                            {tt("badge.conflicting")}
                          </span>
                        </div>
                        <h4
                          className="truncate text-sm font-bold text-[#1b1b24]"
                          title={citation.filename ?? tc("unknownDocument")}
                        >
                          {citation.filename ?? tc("unknownDocument")}
                        </h4>
                        {citation.page_number ? (
                          <p className="text-[9px] text-[#464555]">
                            {tc("citationPositionPage", {
                              page: citation.page_number,
                            })}
                          </p>
                        ) : null}
                      </button>
                    ))}
                </div>
              </div>
            </div>
          </div>
        ) : selectedCitationTurn.response.not_found ? (
          <p className="text-xs text-[#777587]">{tc("sourceDocsNotFound")}</p>
        ) : selectedCitationTurn.response.citations.length === 0 ? (
          <p className="text-xs text-[#777587]">{tc("sourceDocsNone")}</p>
        ) : (
          <div className="space-y-2">
            {selectedCitationTurn.response.citations.map((citation, ci) => (
              <button
                key={`hub:${citation.document_id}:${citation.chunk_id}:${ci}`}
                type="button"
                onClick={() => {
                  const siblings =
                    selectedCitationTurn.response.citations.filter(
                      (c) => c.document_id === citation.document_id,
                    );
                  setPreviewCitationSet({
                    citations: siblings.length > 0 ? siblings : [citation],
                    initialIndex: Math.max(0, siblings.indexOf(citation)),
                  });
                  setIsKnowledgeHubOpen(false);
                }}
                className="group w-full rounded-lg border border-[#c7c4d8] bg-white p-3 text-left transition-all hover:border-[#3525cd]"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span
                    className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                  >
                    {getFileTypeLabel(citation.filename)}
                  </span>
                  <span
                    className="material-symbols-outlined text-xs text-[#464555] group-hover:text-[#3525cd]"
                    aria-hidden="true"
                  >
                    open_in_new
                  </span>
                </div>
                <h4
                  className="mb-1 truncate text-sm font-bold text-[#1b1b24]"
                  title={citation.filename ?? tc("unknownDocument")}
                >
                  {citation.filename ?? tc("unknownDocument")}
                </h4>
                <div className="flex items-center gap-2">
                  {citation.page_number ? (
                    <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-[9px]">
                      {tc("citationPageUpper", {
                        page: citation.page_number,
                      })}
                    </span>
                  ) : null}
                  <span className="text-[9px] text-[#464555]">
                    {tc("citationScoreLower", {
                      score: formatScore(citation.score),
                    })}
                  </span>
                </div>
              </button>
            ))}
            {selectedCitationPipelineHref ? (
              <Link
                href={selectedCitationPipelineHref}
                className="mt-1 flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-[#777587] py-2 text-xs font-bold text-[#464555] transition-all hover:border-[#3525cd] hover:bg-white hover:text-[#3525cd]"
              >
                {tc("viewPipelineRun")}
              </Link>
            ) : null}
          </div>
        )}

        <AgentRunTimeline
          agentRun={agentRun}
          canDecideApprovals={canDecideApprovals}
        />

        <RetrievalDebug
          selectedCitationTurn={selectedCitationTurn}
          showDebugDetails={showDebugDetails}
        />
      </div>
    </>
  );
}
