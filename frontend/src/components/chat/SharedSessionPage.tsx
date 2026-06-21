"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSharedSession } from "@/lib/api/shares";
import { getApiErrorMessage } from "@/lib/api/errors";
import { isForbiddenError } from "@/lib/forbidden";
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
): { label: string; className: string } | null {
  const trust = citation.source_trust_status ?? null;
  if (!trust) {
    return null;
  }
  if (trust === "expired") {
    return {
      label: "Expired",
      className:
        "rounded-full bg-rose-100 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  }
  if (trust === "archived") {
    return {
      label: "Archived",
      className:
        "rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 uppercase",
    };
  }
  if (trust === "stale" || trust === "revoked" || trust === "deleted") {
    return {
      label: "Stale",
      className:
        "rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  return null;
}

function CitationCard({ citation }: { citation: ChatCitationResponse }) {
  const providerLabel =
    citation.source_provider_label ?? citation.source_provider ?? null;
  const sourceTitle = citation.source_title ?? citation.filename ?? "Document";
  const sourceSection = citation.source_section ?? null;
  const trustStatus = citation.source_trust_status ?? null;
  const freshness = freshnessLabel(citation);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-[#c7c4d8] bg-white p-2">
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
            Page {citation.page_number}
          </p>
        )}
        {citation.text_snippet && (
          <p className="mt-0.5 line-clamp-2 text-[10px] text-[#464555]">
            {citation.text_snippet}
          </p>
        )}
      </div>
    </div>
  );
}

export function SharedSessionPage({ token }: Props) {
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
        <LoadingState title="Loading shared session..." />
      </section>
    );
  }

  if (sharedQuery.isError) {
    if (isForbiddenError(sharedQuery.error)) {
      return (
        <section className="px-4 py-8">
          <ForbiddenState
            title="Access denied"
            description="This share link is not accessible with your account. You must be a member of the organization that created it."
            compact={false}
          />
        </section>
      );
    }
    return (
      <section className="px-4 py-8">
        <ErrorState
          title="Share link not found"
          error={sharedQuery.error}
          description={getApiErrorMessage(sharedQuery.error)}
        />
      </section>
    );
  }

  const data = sharedQuery.data;
  if (!data) return null;

  const sessionTitle = data.title?.trim() || "Shared session";

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
              Shared Session
            </p>
            <h1 className="truncate text-xl font-semibold text-[#2a2640] lg:text-2xl">
              {sessionTitle}
            </h1>
            <p className="mt-1 text-xs text-[#6a6780]">
              Shared {formatDate(data.shared_at)} • {data.total_messages}{" "}
              messages
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
              Copy all
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
              Download .md
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
            Answers are AI-generated and grounded in cited source evidence.
            Verify against source documents before acting on them.
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
              Some citations in this shared session come from stale, expired,
              or archived sources.
            </div>
          ) : null}

          {turns.length === 0 ? (
            <EmptyState compact title="No messages in this shared session." />
          ) : (
            <ul className="space-y-6">
              {turns.map((turn, i) => (
                <li key={`${i}-${turn.created_at}`} className="space-y-3">
                  <div className="flex justify-end">
                    <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                      <p className="sr-only">Question</p>
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
                          AI-generated answer
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
    </section>
  );
}
