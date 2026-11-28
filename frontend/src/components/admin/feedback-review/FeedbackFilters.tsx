"use client";

import {
  type FeedbackReviewStatus,
  type FeedbackSeverity,
} from "@/lib/api/feedback-review";
import { useFeedbackReviewController } from "@/components/admin/feedback-review/useFeedbackReviewController";

export function FeedbackFilters({
  ctl,
}: {
  ctl: ReturnType<typeof useFeedbackReviewController>;
}) {
  const {
    t,
    statusInput,
    setStatusInput,
    categoryInput,
    setCategoryInput,
    workspaceInput,
    setWorkspaceInput,
    documentInput,
    setDocumentInput,
    modelInput,
    setModelInput,
    confidenceMinInput,
    setConfidenceMinInput,
    confidenceMaxInput,
    setConfidenceMaxInput,
    severityInput,
    setSeverityInput,
    ratingInput,
    setRatingInput,
    reasonInput,
    setReasonInput,
    applyFilters,
    clearFilters,
  } = ctl;

  return (
    <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
      <form className="flex flex-wrap items-end gap-3" onSubmit={applyFilters}>
        <label className="w-[180px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.status")}
          </span>
          <select
            value={statusInput}
            onChange={(e) =>
              setStatusInput(e.target.value as FeedbackReviewStatus | "")
            }
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          >
            <option value="">{t("filters.allStatuses")}</option>
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

        <label className="w-[180px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.category")}
          </span>
          <input
            value={categoryInput}
            onChange={(e) => setCategoryInput(e.target.value)}
            placeholder={t("placeholders.category")}
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[220px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.workspaceId")}
          </span>
          <input
            value={workspaceInput}
            onChange={(e) => setWorkspaceInput(e.target.value)}
            placeholder={t("placeholders.currentWorkspace")}
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[220px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.documentId")}
          </span>
          <input
            value={documentInput}
            onChange={(e) => setDocumentInput(e.target.value)}
            placeholder={t("placeholders.documentUuid")}
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[180px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.model")}
          </span>
          <input
            value={modelInput}
            onChange={(e) => setModelInput(e.target.value)}
            placeholder="gpt-4o"
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[120px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.minConfidence")}
          </span>
          <input
            value={confidenceMinInput}
            onChange={(e) => setConfidenceMinInput(e.target.value)}
            placeholder="0.0"
            inputMode="decimal"
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[120px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.maxConfidence")}
          </span>
          <input
            value={confidenceMaxInput}
            onChange={(e) => setConfidenceMaxInput(e.target.value)}
            placeholder="1.0"
            inputMode="decimal"
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          />
        </label>

        <label className="w-[150px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.severity")}
          </span>
          <select
            value={severityInput}
            onChange={(e) =>
              setSeverityInput(e.target.value as FeedbackSeverity | "")
            }
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          >
            <option value="">{t("filters.allSeverities")}</option>
            <option value="high">{t("severities.high")}</option>
            <option value="medium">{t("severities.medium")}</option>
            <option value="low">{t("severities.low")}</option>
          </select>
        </label>

        <label className="w-[140px] space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.rating")}
          </span>
          <select
            value={ratingInput}
            onChange={(e) =>
              setRatingInput(e.target.value as "up" | "down" | "")
            }
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          >
            <option value="">{t("filters.allRatings")}</option>
            <option value="down">{t("ratings.down")}</option>
            <option value="up">{t("ratings.up")}</option>
          </select>
        </label>

        <label className="min-w-[180px] flex-1 space-y-1">
          <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("fields.reason")}
          </span>
          <select
            value={reasonInput}
            onChange={(e) => setReasonInput(e.target.value)}
            className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
          >
            <option value="">{t("filters.allReasons")}</option>
            <option value="wrong_citation">{t("reasons.wrongCitation")}</option>
            <option value="hallucination">{t("reasons.hallucination")}</option>
            <option value="outdated_source">
              {t("reasons.outdatedSource")}
            </option>
            <option value="missing_document">
              {t("reasons.missingDocument")}
            </option>
            <option value="unsafe_content">{t("reasons.unsafeContent")}</option>
            <option value="other">{t("reasons.other")}</option>
          </select>
        </label>

        <button
          type="submit"
          className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8]"
        >
          {t("actions.apply")}
        </button>
        <button
          type="button"
          onClick={clearFilters}
          className="h-10 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
        >
          {t("actions.clear")}
        </button>
      </form>
    </section>
  );
}
