"use client";

import React, { forwardRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  type FeedbackReviewItemResponse,
  type FeedbackReviewStatus,
  type FeedbackSeverity,
  type UpdateReviewItemPayload,
} from "@/lib/api/feedback-review";
import {
  formatTimestamp,
  categoryLabel,
  trimToNull,
} from "@/components/admin/feedback-review/feedbackReviewShared";

export type DetailPanelProps = {
  item: FeedbackReviewItemResponse;
  onClose: () => void;
  onUpdate: (reviewId: string, payload: UpdateReviewItemPayload) => void;
  onConvert: (reviewId: string) => void;
  onRedact: (feedbackId: string) => void;
  onSaveAsKnowledgeCard: (reviewId: string) => void;
  isUpdating: boolean;
};

export const DetailPanel = forwardRef<HTMLElement, DetailPanelProps>(
  function DetailPanel(
    {
      item,
      onClose,
      onUpdate,
      onConvert,
      onRedact,
      onSaveAsKnowledgeCard,
      isUpdating,
    },
    ref,
  ) {
    const t = useTranslations("adminFeedbackReview");
    const [statusInput, setStatusInput] = useState<FeedbackReviewStatus>(
      item.status,
    );
    const [severityInput, setSeverityInput] = useState<FeedbackSeverity>(
      item.severity,
    );
    const [notesInput, setNotesInput] = useState(item.reviewer_notes ?? "");
    const [reviewerInput, setReviewerInput] = useState(item.reviewer_id ?? "");
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
        reviewer_id: trimToNull(reviewerInput),
        linked_eval_question_id: trimToNull(evalQuestionId),
        linked_document_id: trimToNull(linkedDocId),
      });
    }

    const isRedacted = item.feedback?.redacted_at != null;
    const isConverted = item.feedback?.converted_to_eval_question_id != null;

    return (
      <aside
        ref={ref as React.RefObject<HTMLElement>}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-detail-title"
        className="absolute end-0 top-3 z-20 max-h-[min(85vh,760px)] w-full max-w-[440px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("detail.reviewDetail")}
            </p>
            <h3
              id="review-detail-title"
              className="mt-1 text-base font-semibold text-[#1b1b24]"
            >
              {t("detail.feedbackItem")}
            </h3>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
          >
            {t("actions.close")}
          </button>
        </div>

        {item.feedback ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("detail.originalFeedback")}
            </h4>
            <dl className="grid gap-1 text-sm">
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  {t("fields.rating")}
                </dt>
                <dd className="text-[#302f39]">{item.feedback.rating}</dd>
              </div>
              {item.feedback.category ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.category")}
                  </dt>
                  <dd className="text-[#302f39] capitalize">
                    {categoryLabel(item.feedback.category)}
                  </dd>
                </div>
              ) : null}
              {item.feedback.reason ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.reason")}
                  </dt>
                  <dd className="text-[#302f39]">{item.feedback.reason}</dd>
                </div>
              ) : null}
              {item.feedback.comment ? (
                <div>
                  <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.comment")}
                  </dt>
                  <dd className="mt-1 text-sm text-[#302f39]">
                    {item.feedback.comment}
                  </dd>
                </div>
              ) : null}
              {item.feedback.model_name ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.model")}
                  </dt>
                  <dd className="font-mono text-xs text-[#464555]">
                    {item.feedback.model_name}
                  </dd>
                </div>
              ) : null}
              {item.feedback.llm_provider ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.provider")}
                  </dt>
                  <dd className="font-mono text-xs text-[#464555]">
                    {item.feedback.llm_provider}
                  </dd>
                </div>
              ) : null}
              {item.feedback.confidence_score != null ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.confidence")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {(item.feedback.confidence_score * 100).toFixed(1)}%
                  </dd>
                </div>
              ) : null}
              {item.feedback.citations ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.citations")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {t("detail.capturedCount", {
                      count: item.feedback.citations.length,
                    })}
                  </dd>
                </div>
              ) : null}
              {item.feedback.trace_id ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.trace")}
                  </dt>
                  <dd className="font-mono text-xs text-[#464555]">
                    {item.feedback.trace_id}
                  </dd>
                </div>
              ) : null}
              {item.feedback.trust_metadata ? (
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    {t("fields.trust")}
                  </dt>
                  <dd className="text-[#302f39]">
                    {t("detail.fieldsCount", {
                      count: Object.keys(item.feedback.trust_metadata).length,
                    })}
                  </dd>
                </div>
              ) : null}
              {isRedacted ? (
                <p className="mt-1 text-[10px] text-[#777587] italic">
                  {t("detail.diagnosticsRedacted", {
                    date: formatTimestamp(item.feedback.redacted_at!),
                  })}
                </p>
              ) : null}
              {isConverted ? (
                <p className="mt-1 text-[10px] text-violet-700">
                  {t("detail.convertedToEval")}{" "}
                  <span className="font-mono">
                    {item.feedback.converted_to_eval_question_id}
                  </span>
                </p>
              ) : null}
            </dl>
          </section>
        ) : null}

        {/* Captured question / answer diagnostics */}
        {item.feedback?.question_text && !isRedacted ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("detail.capturedQuestion")}
            </h4>
            <p className="text-sm text-[#302f39]">
              {item.feedback.question_text}
            </p>
          </section>
        ) : null}

        {item.feedback?.answer_text && !isRedacted ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("detail.capturedAnswer")}
            </h4>
            <p className="line-clamp-6 text-sm text-[#302f39]">
              {item.feedback.answer_text}
            </p>
          </section>
        ) : null}

        {item.message && !item.feedback?.question_text ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("detail.originalAnswer")}
            </h4>
            <p className="text-sm text-[#302f39]">
              {item.message.content_preview}
            </p>
            {item.message.confidence_score != null ? (
              <p className="mt-2 text-xs text-[#777587]">
                {t("fields.confidence")}:{" "}
                {(item.message.confidence_score * 100).toFixed(1)}%
                {item.message.model_name ? ` · ${item.message.model_name}` : ""}
                {item.message.latency_ms != null
                  ? ` · ${item.message.latency_ms} ms`
                  : ""}
              </p>
            ) : null}
          </section>
        ) : null}

        {/* F303 / F328 quick actions */}
        {item.review_id ? (
          <div className="mb-4 flex flex-wrap gap-2">
            {!isConverted ? (
              <button
                type="button"
                onClick={() => onConvert(item.review_id)}
                className="rounded-lg border border-violet-300 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 hover:bg-violet-100"
              >
                {t("actions.convertToEval")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onSaveAsKnowledgeCard(item.review_id)}
              className="rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
            >
              {t("actions.saveKnowledgeCard")}
            </button>
            {!isRedacted && item.feedback ? (
              <button
                type="button"
                onClick={() => onRedact(item.feedback!.feedback_id)}
                className="rounded-lg border border-[#c7c4d8] px-3 py-1.5 text-xs font-semibold text-[#777587] hover:bg-[#f5f2ff]"
              >
                {t("actions.redactDiagnostics")}
              </button>
            ) : null}
          </div>
        ) : null}

        <section className="space-y-3">
          <h4 className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("detail.triageActions")}
          </h4>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("fields.status")}
            </span>
            <select
              value={statusInput}
              onChange={(e) =>
                setStatusInput(e.target.value as FeedbackReviewStatus)
              }
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="new">{t("statuses.new")}</option>
              <option value="triaged">{t("statuses.triaged")}</option>
              <option value="accepted">{t("statuses.accepted")}</option>
              <option value="needs_document_update">
                {t("statuses.needsDocumentUpdate")}
              </option>
              <option value="needs_prompt_retrieval_fix">
                {t("statuses.needsPromptRetrievalFix")}
              </option>
              <option value="converted_to_evaluation">
                {t("statuses.convertedToEvaluation")}
              </option>
              <option value="resolved">{t("statuses.resolved")}</option>
              <option value="rejected">{t("statuses.rejected")}</option>
              <option value="duplicate">{t("statuses.duplicate")}</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("fields.severity")}
            </span>
            <select
              value={severityInput}
              onChange={(e) =>
                setSeverityInput(e.target.value as FeedbackSeverity)
              }
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="low">{t("severities.low")}</option>
              <option value="medium">{t("severities.medium")}</option>
              <option value="high">{t("severities.high")}</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("fields.reviewerNotes")}
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
              {t("fields.assigneeReviewerId")}
            </span>
            <input
              value={reviewerInput}
              onChange={(e) => setReviewerInput(e.target.value)}
              placeholder={t("placeholders.optionalUuid")}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("fields.linkedEvalQuestionId")}
            </span>
            <input
              value={evalQuestionId}
              onChange={(e) => setEvalQuestionId(e.target.value)}
              placeholder={t("placeholders.optionalUuid")}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("fields.linkedDocumentId")}
            </span>
            <input
              value={linkedDocId}
              onChange={(e) => setLinkedDocId(e.target.value)}
              placeholder={t("placeholders.optionalUuid")}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>

          <button
            type="button"
            onClick={handleSave}
            disabled={isUpdating}
            className="w-full rounded-lg bg-[#3525cd] px-4 py-2 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isUpdating ? t("actions.saving") : t("actions.saveChanges")}
          </button>

          <div className="rounded-lg border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2 text-xs text-[#777587]">
            <p>
              <span className="font-semibold">{t("fields.reviewId")}:</span>{" "}
              <span className="font-mono">{item.review_id}</span>
            </p>
            <p>
              <span className="font-semibold">{t("fields.created")}:</span>{" "}
              {formatTimestamp(item.created_at)}
            </p>
            {item.resolved_at ? (
              <p>
                <span className="font-semibold">{t("fields.resolved")}:</span>{" "}
                {formatTimestamp(item.resolved_at)}
              </p>
            ) : null}
          </div>
        </section>
      </aside>
    );
  },
);
