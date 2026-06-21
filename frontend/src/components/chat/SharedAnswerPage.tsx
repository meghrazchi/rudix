"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSharedAnswer } from "@/lib/api/answer-shares";
import type { SharedAnswerCitationResponse } from "@/lib/api/answer-shares";
import { getApiErrorMessage } from "@/lib/api/errors";
import { isForbiddenError } from "@/lib/forbidden";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";

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
  citation: SharedAnswerCitationResponse,
): { label: string; className: string } | null {
  if (!citation.source_freshness_warning) {
    return null;
  }
  const reason = (citation.source_freshness_warning_reason ?? "").toLowerCase();
  if (reason.includes("expired")) {
    return {
      label: "Expired",
      className:
        "rounded-full bg-rose-100 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  }
  if (reason.includes("archived")) {
    return {
      label: "Archived",
      className:
        "rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 uppercase",
    };
  }
  return {
    label: "Stale",
    className:
      "rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
  };
}

function CitationCard({
  citation,
}: {
  citation: SharedAnswerCitationResponse;
}) {
  const providerLabel = citation.source_provider_label ?? null;
  const sourceTitle = citation.source_title ?? citation.filename ?? "Document";
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
          {citation.source_trust_status ? (
            <span className="rounded-full bg-[#f0ecf9] px-1.5 py-0.5 text-[9px] font-semibold text-[#5d58a8] uppercase">
              {citation.source_trust_status}
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
        {citation.source_section ? (
          <p className="truncate text-[10px] text-[#6a6780]">
            {citation.source_section}
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

function PasswordGate({
  token,
  onUnlocked,
}: {
  token: string;
  onUnlocked: (password: string) => void;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await getSharedAnswer(token, input);
      onUnlocked(input);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="flex min-h-[40vh] items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <span
            className="material-symbols-outlined text-[22px] text-[#3525cd]"
            aria-hidden="true"
          >
            lock
          </span>
          <h1 className="text-base font-semibold text-[#2a2640]">
            Password required
          </h1>
        </div>
        <p className="mb-4 text-xs text-[#6a6780]">
          This shared answer is password protected. Enter the password to view
          it.
        </p>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Enter password"
            autoFocus
            className="w-full rounded-lg border border-[#d2cee6] px-3 py-2 text-sm text-[#2f2a46] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          />
          {error ? <p className="text-xs text-rose-700">{error}</p> : null}
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="w-full rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Checking..." : "Unlock"}
          </button>
        </form>
      </div>
    </section>
  );
}

export function SharedAnswerPage({ token }: Props) {
  const [unlockedPassword, setUnlockedPassword] = useState<string | undefined>(
    undefined,
  );
  const [needsPassword, setNeedsPassword] = useState(false);

  const sharedQuery = useQuery({
    queryKey: ["chat", "answer-shared", token, unlockedPassword],
    queryFn: () => getSharedAnswer(token, unlockedPassword),
    retry: false,
    enabled: !needsPassword || unlockedPassword !== undefined,
  });

  // Detect password-required 403
  if (
    !needsPassword &&
    sharedQuery.isError &&
    !isForbiddenError(sharedQuery.error)
  ) {
    const msg = getApiErrorMessage(sharedQuery.error).toLowerCase();
    if (msg.includes("password")) {
      setNeedsPassword(true);
    }
  }

  if (needsPassword && unlockedPassword === undefined) {
    return (
      <PasswordGate
        token={token}
        onUnlocked={(pw) => setUnlockedPassword(pw)}
      />
    );
  }

  if (sharedQuery.isLoading) {
    return (
      <section className="px-4 py-8">
        <LoadingState title="Loading shared answer..." />
      </section>
    );
  }

  if (sharedQuery.isError) {
    if (isForbiddenError(sharedQuery.error)) {
      return (
        <section className="px-4 py-8">
          <ForbiddenState
            title="Access denied"
            description="This share link is not accessible with your account."
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

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 px-4 py-4 lg:px-8 lg:py-6">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white px-4 py-4 shadow-sm lg:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Shared Answer
            </p>
            <p className="mt-1 text-xs text-[#6a6780]">
              Shared {formatDate(data.shared_at)}
              {data.expires_at
                ? ` · Expires ${formatDate(data.expires_at)}`
                : ""}
            </p>
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
            This answer is AI-generated and grounded in cited source excerpts.
            Verify against original documents before acting on it.
          </div>
          {data.citations.some((citation) => citation.source_freshness_warning) ? (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Some citations come from stale, expired, or archived sources.
            </div>
          ) : null}

          <div className="space-y-4">
            {/* Question */}
            {data.question ? (
              <div className="flex justify-end">
                <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                  <p className="sr-only">Question</p>
                  <p className="text-sm break-words whitespace-pre-wrap text-[#1b1b24]">
                    {data.question}
                  </p>
                </article>
              </div>
            ) : null}

            {/* Answer */}
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
                  {data.confidence_category ? (
                    <span className="rounded-full bg-[#e4e1ee] px-2 py-0.5 text-[10px] font-semibold text-[#464555] uppercase">
                      {data.confidence_category} confidence
                    </span>
                  ) : null}
                </div>
                <p className="text-sm break-words whitespace-pre-wrap text-[#2f2a46]">
                  {data.answer}
                </p>
                {data.citations.length > 0 && (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {data.citations.map((citation, ci) => (
                      <CitationCard
                        key={`${citation.filename ?? ""}:${ci}`}
                        citation={citation}
                      />
                    ))}
                  </div>
                )}
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
