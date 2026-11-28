"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { getSharedSession } from "@/lib/api/shares";
import { getApiErrorMessage } from "@/lib/api/errors";
import { isForbiddenError } from "@/lib/forbidden";
import { CitationPreviewDrawer } from "@/components/chat/DocumentPreviewModal";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { EmptyState } from "@/components/states/EmptyState";
import {
  turnsFromMessages,
  formatTranscriptAsMarkdown,
  downloadMarkdown,
  sanitizeFilename,
  copyToClipboard,
} from "@/lib/export-utils";
import type { ChatCitationResponse } from "@/lib/api/chat";

type Props = {
  token: string;
};

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function getFileTypeLabel(filename: string | null | undefined): string {
  if (!filename) return "FILE";
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}

function getFileTypeColorClass(filename: string | null | undefined): string {
  if (!filename) return "text-[#464555]";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "text-[#3525cd]";
  if (["md", "txt", "doc", "docx"].includes(ext)) return "text-emerald-600";
  if (["xlsx", "xls", "csv"].includes(ext)) return "text-amber-600";
  return "text-[#464555]";
}

function freshnessLabel(
  citation: ChatCitationResponse,
  t: (key: string) => string,
): { label: string; className: string } | null {
  const trust = citation.source_trust_status ?? null;
  if (!trust) {
    return null;
  }
  if (trust === "stale") {
    return {
      label: t("trustPanel.badge.stale"),
      className:
        "rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  if (trust === "revoked") {
    return {
      label: t("trustPanel.badge.revoked"),
      className:
        "rounded-full bg-rose-100 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  }
  if (trust === "deleted") {
    return {
      label: t("trustPanel.badge.deleted"),
      className:
        "rounded bg-slate-200 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 uppercase",
    };
  }
  return null;
}

function CitationCard({
  citation,
  onClick,
}: {
  citation: ChatCitationResponse;
  onClick?: () => void;
}) {
  const t = useTranslations("chat");
  const providerLabel =
    citation.source_provider_label ?? citation.source_provider ?? null;
  const sourceTitle =
    citation.source_title ?? citation.filename ?? t("share.page.document");
  const sourceSection = citation.source_section ?? null;
  const trustStatus = citation.source_trust_status ?? null;
  const freshness = freshnessLabel(citation, t);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className="flex w-full items-start gap-2 rounded-lg border border-[#c7c4d8] bg-white p-2 text-left transition-colors hover:bg-[#f5f2ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:cursor-default disabled:hover:bg-white"
    >
      <div className="min-w-0 overflow-hidden">
        <div className="mb-0.5 flex flex-wrap items-center gap-1">
          <p
            className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
          >
            {providerLabel
              ? providerLabel.toUpperCase()
              : getFileTypeLabel(citation.filename)}
          </p>
          {trustStatus ? (
            <span className="rounded-full bg-[#f0ecf9] px-1.5 py-0.5 text-[9px] font-semibold text-[#5d58a8] uppercase">
              {trustStatus}
            </span>
          ) : null}
          {freshness ? (
            <span className={freshness.className}>{freshness.label}</span>
          ) : null}
        </div>
        <p
          className="truncate text-xs font-bold text-[#1b1b24]"
          title={sourceTitle}
        >
          {sourceTitle}
        </p>
        {citation.source_key ? (
          <p
            className="truncate font-mono text-[10px] text-[#6a6780]"
            title={citation.source_key}
          >
            {citation.source_key}
          </p>
        ) : null}
        {sourceSection ? (
          <p
            className="truncate text-[10px] text-[#6a6780]"
            title={sourceSection}
          >
            {sourceSection}
          </p>
        ) : null}
        {citation.page_number != null && (
          <p className="text-[10px] text-[#6a6780]">
            {t("share.page.pageN", { page: citation.page_number })}
          </p>
        )}
        {citation.text_snippet && (
          <p className="mt-0.5 line-clamp-2 text-[10px] text-[#464555]">
            {citation.text_snippet}
          </p>
        )}
      </div>
    </button>
  );
}

export function SharedSessionPage({ token }: Props) {
  const t = useTranslations("chat.share.page");
  const [previewCitationSet, setPreviewCitationSet] = useState<{
    citations: ChatCitationResponse[];
    initialIndex: number;
  } | null>(null);
  const sharedQuery = useQuery({
    queryKey: ["chat", "shared", token],
    queryFn: () => getSharedSession(token),
    retry: false,
  });

  const turns = useMemo(
    () => turnsFromMessages(sharedQuery.data?.messages ?? []),
    [sharedQuery.data?.messages],
  );

  if (sharedQuery.isLoading) {
    return (
      <section className="px-4 py-8">
        <LoadingState title={t("loadingSession")} />
      </section>
    );
  }

  if (sharedQuery.isError) {
    if (isForbiddenError(sharedQuery.error)) {
      return (
        <section className="px-4 py-8">
          <ForbiddenState
            title={t("accessDenied")}
            description={t("sessionForbidden")}
            compact={false}
          />
        </section>
      );
    }
    return (
      <section className="px-4 py-8">
        <ErrorState
          title={t("notFound")}
          error={sharedQuery.error}
          description={getApiErrorMessage(sharedQuery.error)}
        />
      </section>
    );
  }

  const data = sharedQuery.data;
  if (!data) return null;

  const sessionTitle = data.title?.trim() || t("sessionFallbackTitle");

  function handleDownload() {
    const md = formatTranscriptAsMarkdown(turns, sessionTitle);
    downloadMarkdown(md, `${sanitizeFilename(sessionTitle)}.md`);
  }

  async function handleCopyAll() {
    const md = formatTranscriptAsMarkdown(turns, sessionTitle);
    await copyToClipboard(md);
  }

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 px-4 py-4 lg:px-8 lg:py-6">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white px-4 py-4 shadow-sm lg:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              {t("sessionHeading")}
            </p>
            <h1 className="truncate text-xl font-semibold text-[#2a2640] lg:text-2xl">
              {sessionTitle}
            </h1>
            <p className="mt-1 text-xs text-[#6a6780]">
              {t("sharedMessages", {
                date: formatDate(data.shared_at),
                count: data.total_messages,
              })}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void handleCopyAll()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden="true"
              >
                content_copy
              </span>
              {t("copyAll")}
            </button>
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
            >
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden="true"
              >
                download
              </span>
              {t("downloadMd")}
            </button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="hide-scrollbar h-full overflow-y-auto p-4">
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <span
              className="material-symbols-outlined mr-1 align-middle text-[14px]"
              aria-hidden="true"
            >
              info
            </span>
            {t("aiNoticeSession")}
          </div>
          {turns.some((turn) =>
            turn.citations.some(
              (citation) =>
                citation.doc_stale_warning ||
                citation.doc_expired_warning ||
                citation.doc_is_excluded_status,
            ),
          ) ? (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t("staleSession")}
            </div>
          ) : null}

          {turns.length === 0 ? (
            <EmptyState compact title={t("noMessages")} />
          ) : (
            <ul className="space-y-6">
              {turns.map((turn, i) => (
                <li key={`${i}-${turn.created_at}`} className="space-y-3">
                  <div className="flex justify-end">
                    <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                      <p className="sr-only">{t("question")}</p>
                      <p className="text-sm break-words whitespace-pre-wrap text-[#1b1b24]">
                        {turn.question}
                      </p>
                    </article>
                  </div>

                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#3525cd] text-white">
                      <span
                        className="material-symbols-outlined text-[18px]"
                        aria-hidden="true"
                        style={{ fontVariationSettings: "'FILL' 1" }}
                      >
                        auto_awesome
                      </span>
                    </div>
                    <article className="max-w-[92%] flex-1 rounded-xl rounded-tl-none border border-[#c7c4d8] bg-[#f0ecf9] px-4 py-3 shadow-sm">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="inline-flex items-center gap-1 rounded-full bg-[#e4e1ee] px-2 py-1 text-xs font-bold tracking-wide text-emerald-800 uppercase">
                          <span
                            className="material-symbols-outlined text-xs"
                            aria-hidden="true"
                            style={{ fontVariationSettings: "'FILL' 1" }}
                          >
                            check_circle
                          </span>
                          {t("aiAnswer")}
                        </span>
                        <span className="font-mono text-xs text-[#6a6780]">
                          {formatDate(turn.created_at)}
                        </span>
                      </div>
                      <p className="text-sm break-words whitespace-pre-wrap text-[#2f2a46]">
                        {turn.answer}
                      </p>
                      {turn.citations.length > 0 && (
                        <div className="mt-3 grid grid-cols-2 gap-2">
                          {turn.citations.map((citation, ci) => (
                            <CitationCard
                              key={`${citation.document_id}:${citation.chunk_id}:${ci}`}
                              citation={citation}
                              onClick={() => {
                                const siblings = turn.citations.filter(
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
                              }}
                            />
                          ))}
                        </div>
                      )}
                    </article>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {previewCitationSet ? (
        <CitationPreviewDrawer
          citations={previewCitationSet.citations}
          initialIndex={previewCitationSet.initialIndex}
          onClose={() => setPreviewCitationSet(null)}
        />
      ) : null}
    </section>
  );
}
