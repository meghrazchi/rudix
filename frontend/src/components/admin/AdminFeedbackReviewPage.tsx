"use client";

import React, {
  forwardRef,
  useCallback,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  buildFeedbackReviewExportUrl,
  listFeedbackReviewItems,
  triageFeedback,
  updateFeedbackReviewItem,
  type FeedbackReviewItemResponse,
  type FeedbackReviewListParams,
  type FeedbackReviewStatus,
  type FeedbackSeverity,
  type UpdateReviewItemPayload,
} from "@/lib/api/feedback-review";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError, extractRequestIdFromError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

const PAGE_LIMIT = 20;

type AppliedFilters = {
  status: FeedbackReviewStatus | null;
  severity: FeedbackSeverity | null;
  rating: "up" | "down" | null;
  reason: string | null;
};

const DEFAULT_FILTERS: AppliedFilters = {
  status: null,
  severity: null,
  rating: null,
  reason: null,
};

function formatTimestamp(value: string): string {
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  return new Date(ts).toLocaleString();
}

function statusPillClass(s: FeedbackReviewStatus): string {
  switch (s) {
    case "fixed":
      return "bg-emerald-100 text-emerald-800";
    case "rejected":
    case "duplicate":
      return "bg-slate-200 text-slate-700";
    case "eval_created":
      return "bg-violet-100 text-violet-800";
    case "needs_document":
      return "bg-amber-100 text-amber-800";
    case "triaged":
      return "bg-blue-100 text-blue-800";
    default:
      return "bg-rose-100 text-rose-800";
  }
}

function severityPillClass(s: FeedbackSeverity): string {
  switch (s) {
    case "high":
      return "bg-rose-100 text-rose-800";
    case "medium":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function trimToNull(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function triggerCsvDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "feedback-review-queue.csv";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

type DetailPanelProps = {
  item: FeedbackReviewItemResponse;
  onClose: () => void;
  onUpdate: (reviewId: string, payload: UpdateReviewItemPayload) => void;
  isUpdating: boolean;
};

const DetailPanel = forwardRef<HTMLElement, DetailPanelProps>(
  function DetailPanel({ item, onClose, onUpdate, isUpdating }, ref) {
    const [statusInput, setStatusInput] = useState<FeedbackReviewStatus>(
      item.status,
    );
    const [severityInput, setSeverityInput] = useState<FeedbackSeverity>(
      item.severity,
    );
    const [notesInput, setNotesInput] = useState(item.reviewer_notes ?? "");
    const [evalQuestionId, setEvalQuestionId] = useState(
      item.linked_eval_question_id ?? "",
    );
    const [linkedDocId, setLinkedDocId] = useState(
      item.linked_document_id ?? "",
    );

    function handleSave() {
      onUpdate(item.review_id, {
        status: statusInput,
        severity: severityInput,
        reviewer_notes: trimToNull(notesInput),
        linked_eval_question_id: trimToNull(evalQuestionId),
        linked_document_id: trimToNull(linkedDocId),
      });
    }

    return (
      <aside
        ref={ref as React.RefObject<HTMLElement>}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-detail-title"
        className="absolute top-3 right-0 z-20 max-h-[min(85vh,760px)] w-full max-w-[440px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Review detail
            </p>
            <h3
              id="review-detail-title"
              className="mt-1 text-base font-semibold text-[#1b1b24]"
            >
              Feedback item
            </h3>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
          >
            Close
          </button>
        </div>

        {item.feedback ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Original feedback
            </h4>
            <dl className="grid gap-1 text-sm">
              <div className="flex gap-2">
                <dt className="w-16 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Rating
                </dt>
                <dd className="text-[#302f39]">{item.feedback.rating}</dd>
              </div>
              {item.feedback.reason ? (
                <div className="flex gap-2">
                  <dt className="w-16 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    Reason
                  </dt>
                  <dd className="text-[#302f39]">{item.feedback.reason}</dd>
                </div>
              ) : null}
              {item.feedback.comment ? (
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    Comment
                  </dt>
                  <dd className="mt-1 text-sm text-[#302f39]">
                    {item.feedback.comment}
                  </dd>
                </div>
              ) : null}
            </dl>
          </section>
        ) : null}

        {item.message ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Original answer
            </h4>
            <p className="text-sm text-[#302f39]">
              {item.message.content_preview}
            </p>
            {item.message.confidence_score != null ? (
              <p className="mt-2 text-xs text-[#777587]">
                Confidence: {(item.message.confidence_score * 100).toFixed(1)}%
                {item.message.model_name ? ` · ${item.message.model_name}` : ""}
                {item.message.latency_ms != null
                  ? ` · ${item.message.latency_ms} ms`
                  : ""}
              </p>
            ) : null}
          </section>
        ) : null}

        <section className="space-y-3">
          <h4 className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            Triage actions
          </h4>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Status
            </span>
            <select
              value={statusInput}
              onChange={(e) =>
                setStatusInput(e.target.value as FeedbackReviewStatus)
              }
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="new">New</option>
              <option value="triaged">Triaged</option>
              <option value="needs_document">Needs document</option>
              <option value="eval_created">Eval created</option>
              <option value="fixed">Fixed</option>
              <option value="rejected">Rejected</option>
              <option value="duplicate">Duplicate</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Severity
            </span>
            <select
              value={severityInput}
              onChange={(e) =>
                setSeverityInput(e.target.value as FeedbackSeverity)
              }
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Reviewer notes
            </span>
            <textarea
              value={notesInput}
              onChange={(e) => setNotesInput(e.target.value)}
              rows={3}
              maxLength={4000}
              className="w-full resize-none rounded-lg border border-[#c7c4d8] bg-white px-3 py-2 text-sm text-[#1b1b24]"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Linked eval question ID
            </span>
            <input
              value={evalQuestionId}
              onChange={(e) => setEvalQuestionId(e.target.value)}
              placeholder="UUID (optional)"
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Linked document ID
            </span>
            <input
              value={linkedDocId}
              onChange={(e) => setLinkedDocId(e.target.value)}
              placeholder="UUID (optional)"
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <button
            type="button"
            onClick={handleSave}
            disabled={isUpdating}
            className="w-full rounded-lg bg-[#3525cd] px-4 py-2 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isUpdating ? "Saving..." : "Save changes"}
          </button>

          <div className="rounded-lg border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2 text-xs text-[#777587]">
            <p>
              <span className="font-semibold">Review ID:</span>{" "}
              <span className="font-mono">{item.review_id}</span>
            </p>
            <p>
              <span className="font-semibold">Created:</span>{" "}
              {formatTimestamp(item.created_at)}
            </p>
            {item.resolved_at ? (
              <p>
                <span className="font-semibold">Resolved:</span>{" "}
                {formatTimestamp(item.resolved_at)}
              </p>
            ) : null}
          </div>
        </section>
      </aside>
    );
  },
);

export function AdminFeedbackReviewPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const [statusInput, setStatusInput] = useState<FeedbackReviewStatus | "">("");
  const [severityInput, setSeverityInput] = useState<FeedbackSeverity | "">("");
  const [ratingInput, setRatingInput] = useState<"up" | "down" | "">("");
  const [reasonInput, setReasonInput] = useState("");
  const [appliedFilters, setAppliedFilters] =
    useState<AppliedFilters>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);
  const [selectedItem, setSelectedItem] =
    useState<FeedbackReviewItemResponse | null>(null);

  const panelRef = useRef<HTMLElement | null>(null);
  const tableHostRef = useRef<HTMLDivElement | null>(null);

  const closePanel = useCallback(() => setSelectedItem(null), []);
  useOverlayFocus({
    isOpen: selectedItem != null,
    containerRef: panelRef,
    onClose: closePanel,
    lockBodyScroll: false,
  });

  const queryParams = useMemo(
    (): FeedbackReviewListParams => ({
      status: appliedFilters.status ?? undefined,
      severity: appliedFilters.severity ?? undefined,
      rating: appliedFilters.rating ?? undefined,
      reason: appliedFilters.reason ?? undefined,
      limit: PAGE_LIMIT,
      offset,
    }),
    [appliedFilters, offset],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.feedbackReview.list(
      queryParams as Record<string, unknown>,
    ),
    queryFn: () => listFeedbackReviewItems(queryParams),
    enabled: isAdminUser,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      reviewId,
      payload,
    }: {
      reviewId: string;
      payload: UpdateReviewItemPayload;
    }) => updateFeedbackReviewItem(reviewId, payload),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedbackReview.all,
      });
      setSelectedItem(updated);
    },
  });

  const forbiddenError =
    listQuery.isError && isForbiddenError(listQuery.error)
      ? listQuery.error
      : null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Feedback review queue restricted"
          description="Only owner and admin roles can access the feedback review queue."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Feedback review queue unavailable"
          description="Your role no longer has access to this queue."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const data = listQuery.data;
  const rows = data?.items ?? [];
  const pageTotal = data?.total ?? 0;
  const pageStart = pageTotal === 0 ? 0 : offset + 1;
  const pageEnd =
    pageTotal === 0 ? 0 : Math.min(offset + PAGE_LIMIT, pageTotal);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + PAGE_LIMIT < pageTotal;

  const openCount = rows.filter(
    (r) => r.status === "new" || r.status === "triaged",
  ).length;
  const highSeverityCount = rows.filter((r) => r.severity === "high").length;
  const resolvedCount = rows.filter(
    (r) =>
      r.status === "fixed" ||
      r.status === "rejected" ||
      r.status === "duplicate",
  ).length;

  function applyFilters(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setOffset(0);
    setAppliedFilters({
      status: (statusInput as FeedbackReviewStatus) || null,
      severity: (severityInput as FeedbackSeverity) || null,
      rating: (ratingInput as "up" | "down") || null,
      reason: trimToNull(reasonInput),
    });
  }

  function clearFilters() {
    setStatusInput("");
    setSeverityInput("");
    setRatingInput("");
    setReasonInput("");
    setOffset(0);
    setAppliedFilters(DEFAULT_FILTERS);
  }

  const exportUrl = buildFeedbackReviewExportUrl({
    status: appliedFilters.status,
    severity: appliedFilters.severity,
    rating: appliedFilters.rating,
    reason: appliedFilters.reason,
  });

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              Quality &amp; Knowledge Gaps
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              Feedback review queue
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              Triage answer feedback, assign severity, link evaluation cases,
              and track resolution of knowledge gaps.
            </p>
          </div>
          <button
            type="button"
            onClick={() => triggerCsvDownload(exportUrl)}
            className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
          >
            Export CSV
          </button>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            Open items (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {openCount}
          </p>
        </article>
        <article className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-amber-700 uppercase">
            High severity (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-amber-700">
            {highSeverityCount}
          </p>
        </article>
        <article className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            Resolved (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-emerald-700">
            {resolvedCount}
          </p>
        </article>
      </section>

      <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={applyFilters}
        >
          <label className="w-[180px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Status
            </span>
            <select
              value={statusInput}
              onChange={(e) =>
                setStatusInput(e.target.value as FeedbackReviewStatus | "")
              }
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All statuses</option>
              <option value="new">New</option>
              <option value="triaged">Triaged</option>
              <option value="needs_document">Needs document</option>
              <option value="eval_created">Eval created</option>
              <option value="fixed">Fixed</option>
              <option value="rejected">Rejected</option>
              <option value="duplicate">Duplicate</option>
            </select>
          </label>

          <label className="w-[150px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Severity
            </span>
            <select
              value={severityInput}
              onChange={(e) =>
                setSeverityInput(e.target.value as FeedbackSeverity | "")
              }
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All severities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label className="w-[140px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Rating
            </span>
            <select
              value={ratingInput}
              onChange={(e) =>
                setRatingInput(e.target.value as "up" | "down" | "")
              }
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All ratings</option>
              <option value="down">Thumbs down</option>
              <option value="up">Thumbs up</option>
            </select>
          </label>

          <label className="min-w-[180px] flex-1 space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Reason
            </span>
            <select
              value={reasonInput}
              onChange={(e) => setReasonInput(e.target.value)}
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All reasons</option>
              <option value="wrong_citation">Wrong citation</option>
              <option value="hallucination">Hallucination</option>
              <option value="outdated_source">Outdated source</option>
              <option value="missing_document">Missing document</option>
              <option value="unsafe_content">Unsafe content</option>
              <option value="other">Other</option>
            </select>
          </label>

          <button
            type="submit"
            className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8]"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={clearFilters}
            className="h-10 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
          >
            Clear
          </button>
        </form>
      </section>

      <div ref={tableHostRef} className="relative">
        <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Review queue
            </h2>
            {listQuery.isSuccess ? (
              <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Showing {pageStart}–{pageEnd} of {pageTotal}
              </p>
            ) : null}
          </div>

          {listQuery.isLoading ? (
            <LoadingState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
              title="Loading feedback items..."
            />
          ) : null}

          {listQuery.isError ? (
            <div className="m-4">
              <ErrorState
                compact
                error={listQuery.error}
                description={getApiErrorMessage(listQuery.error)}
                onRetry={() => {
                  void listQuery.refetch();
                }}
              />
            </div>
          ) : null}

          {listQuery.isSuccess && rows.length === 0 ? (
            <EmptyState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
              title="No feedback items match the current filters."
            />
          ) : null}

          {listQuery.isSuccess && rows.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                    <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      <th className="px-4 py-3">Submitted</th>
                      <th className="px-4 py-3">Rating</th>
                      <th className="px-4 py-3">Reason</th>
                      <th className="px-4 py-3 text-center">Status</th>
                      <th className="px-4 py-3 text-center">Severity</th>
                      <th className="px-4 py-3">Answer preview</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#ece9f5]">
                    {rows.map((item) => {
                      const isSelected =
                        selectedItem?.review_id === item.review_id;
                      return (
                        <tr
                          key={item.review_id}
                          onClick={() => setSelectedItem(item)}
                          className={`cursor-pointer transition-colors ${isSelected ? "bg-[#ebe8ff]" : "hover:bg-[#f5f2ff]"}`}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                            {item.feedback
                              ? formatTimestamp(item.feedback.submitted_at)
                              : formatTimestamp(item.created_at)}
                          </td>
                          <td className="px-4 py-3 text-sm font-medium">
                            {item.feedback?.rating === "down" ? (
                              <span className="text-rose-700">Thumbs down</span>
                            ) : item.feedback?.rating === "up" ? (
                              <span className="text-emerald-700">
                                Thumbs up
                              </span>
                            ) : (
                              <span className="text-[#777587]">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-sm text-[#302f39]">
                            {item.feedback?.reason ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${statusPillClass(item.status)}`}
                            >
                              {item.status.replace(/_/g, " ")}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${severityPillClass(item.severity)}`}
                            >
                              {item.severity}
                            </span>
                          </td>
                          <td className="max-w-[240px] px-4 py-3 text-xs text-[#464555]">
                            <span className="line-clamp-2">
                              {item.message?.content_preview ?? "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedItem(item);
                              }}
                              className="rounded-lg border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                            >
                              Review
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between gap-3 border-t border-[#e4e1ee] px-4 py-3">
                <p className="text-sm text-[#464555]">
                  Showing {pageStart} to {pageEnd} of {pageTotal} items
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setOffset((p) => Math.max(0, p - PAGE_LIMIT))
                    }
                    disabled={!hasPreviousPage || listQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() => setOffset((p) => p + PAGE_LIMIT)}
                    disabled={!hasNextPage || listQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {selectedItem ? (
          <>
            <button
              type="button"
              aria-label="Close review detail"
              onClick={closePanel}
              className="absolute inset-0 z-10 bg-[#17172a]/15 xl:bg-transparent"
            />
            <DetailPanel
              ref={panelRef}
              item={selectedItem}
              onClose={closePanel}
              onUpdate={(reviewId, payload) =>
                updateMutation.mutate({ reviewId, payload })
              }
              isUpdating={updateMutation.isPending}
            />
          </>
        ) : null}
      </div>

      {updateMutation.isError ? (
        <p className="text-sm text-rose-700">
          {getApiErrorMessage(updateMutation.error)}
        </p>
      ) : null}
    </section>
  );
}
