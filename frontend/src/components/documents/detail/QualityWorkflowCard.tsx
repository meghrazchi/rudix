"use client";

import type { DocumentQualityState } from "@/lib/api/documents";

import { MetricCard } from "@/components/documents/detail/MetricCard";
import {
  formatDate,
  qualityBadge,
} from "@/components/documents/detail/detail-format";
import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Freshness and quality warnings, the quality workflow editor, and quality metrics. */
export function QualityWorkflowCard({
  ctl,
  detail,
}: Omit<DetailSectionProps, "currentStatus">) {
  const {
    td,
    capabilities,
    qualityStateDraft,
    setQualityStateDraft,
    qualityNotesDraft,
    setQualityNotesDraft,
    qualityOwnerDraft,
    setQualityOwnerDraft,
    qualityReviewerDraft,
    setQualityReviewerDraft,
    qualityDueDateDraft,
    setQualityDueDateDraft,
    qualityExpiryDateDraft,
    setQualityExpiryDateDraft,
    qualityReviewDateDraft,
    setQualityReviewDateDraft,
    qualityTrustLevelDraft,
    setQualityTrustLevelDraft,
    qualityMutation,
    saveQualityMetadata,
  } = ctl;
  return (
    <>
      {detail.review_status &&
      ["stale", "expired", "needs_review", "archived"].includes(
        detail.review_status,
      ) ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {td("freshnessWarning", {
            status: td(`freshnessStatuses.${detail.review_status}`),
          })}
        </p>
      ) : null}
      {detail.quality_state &&
      [
        "draft",
        "unreviewed",
        "stale",
        "expired",
        "deprecated",
        "archived",
      ].includes(detail.quality_state) ? (
        <p className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800">
          {td("qualityWarning", {
            status: td(`qualityStates.${detail.quality_state}`),
          })}
        </p>
      ) : null}
      {capabilities.canEditQuality ? (
        <div className="rounded-lg border border-violet-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                {td("qualityWorkflow")}
              </h4>
              <p className="mt-1 text-sm text-[#605d73]">
                {td("qualityWorkflowDescription")}
              </p>
            </div>
            <button
              type="button"
              disabled={qualityMutation.isPending}
              onClick={() => {
                void saveQualityMetadata();
              }}
              className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {qualityMutation.isPending ? td("saving") : td("saveQuality")}
            </button>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("qualityState")}
              <select
                value={qualityStateDraft}
                onChange={(event) =>
                  setQualityStateDraft(
                    event.target.value as DocumentQualityState,
                  )
                }
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {[
                  "draft",
                  "verified",
                  "reviewed",
                  "unreviewed",
                  "stale",
                  "expired",
                  "deprecated",
                  "archived",
                ].map((option) => (
                  <option key={option} value={option}>
                    {td(`qualityStates.${option}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("qualityOwnerId")}
              <input
                type="text"
                value={qualityOwnerDraft}
                onChange={(event) => setQualityOwnerDraft(event.target.value)}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("reviewerId")}
              <input
                type="text"
                value={qualityReviewerDraft}
                onChange={(event) =>
                  setQualityReviewerDraft(event.target.value)
                }
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("reviewDue")}
              <input
                type="date"
                value={qualityDueDateDraft}
                onChange={(event) => setQualityDueDateDraft(event.target.value)}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("reviewDate")}
              <input
                type="date"
                value={qualityReviewDateDraft}
                onChange={(event) =>
                  setQualityReviewDateDraft(event.target.value)
                }
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("expiryDate")}
              <input
                type="date"
                value={qualityExpiryDateDraft}
                onChange={(event) =>
                  setQualityExpiryDateDraft(event.target.value)
                }
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("trustLevel")}
              <input
                type="text"
                value={qualityTrustLevelDraft}
                onChange={(event) =>
                  setQualityTrustLevelDraft(event.target.value)
                }
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </label>
          </div>
          <label className="mt-3 grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("qualityNotes")}
            <textarea
              value={qualityNotesDraft}
              onChange={(event) => setQualityNotesDraft(event.target.value)}
              rows={4}
              className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </label>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard label={td("pageCount")} value={detail.page_count ?? "-"} />
        <MetricCard label={td("chunkCount")} value={detail.chunk_count} />
        <MetricCard
          label={td("fileType")}
          value={detail.file_type.toUpperCase()}
        />
        <MetricCard
          label={td("updatedMetric")}
          value={formatDate(detail.updated_at)}
        />
        <MetricCard
          label={td("quality")}
          value={td(`qualityStates.${detail.quality_state ?? "unreviewed"}`)}
          valueClass={qualityBadge(detail.quality_state)}
          plain={false}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          label={td("qualityOwner")}
          value={detail.review_owner_id ?? "-"}
          mono
        />
        <MetricCard
          label={td("reviewer")}
          value={detail.trusted_by_id ?? "-"}
          mono
        />
        <MetricCard
          label={td("reviewDue")}
          value={formatDate(detail.review_due_date)}
        />
        <MetricCard
          label={td("expiryDate")}
          value={formatDate(detail.expiry_date)}
        />
        <MetricCard
          label={td("trustLevel")}
          value={detail.trust_level ?? "-"}
        />
      </div>
      {detail.quality_notes ? (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-900">
          <p className="font-semibold">{td("qualityNotes")}</p>
          <p className="mt-1 whitespace-pre-wrap">{detail.quality_notes}</p>
        </div>
      ) : null}
    </>
  );
}
