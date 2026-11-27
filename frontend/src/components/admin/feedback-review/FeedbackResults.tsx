"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  PAGE_LIMIT,
  formatTimestamp,
  statusPillClass,
  severityPillClass,
  categoryLabel,
} from "@/components/admin/feedback-review/feedbackReviewShared";
import { DetailPanel } from "@/components/admin/feedback-review/DetailPanel";
import { useFeedbackReviewController } from "@/components/admin/feedback-review/useFeedbackReviewController";

export function FeedbackResults({
  ctl,
}: {
  ctl: ReturnType<typeof useFeedbackReviewController>;
}) {
  const {
    t,
    setOffset,
    selectedItem,
    setSelectedItem,
    setConvertReviewId,
    setSaveKnowledgeCardReviewId,
    panelRef,
    tableHostRef,
    closePanel,
    listQuery,
    updateMutation,
    redactMutation,
    rows,
    pageTotal,
    pageStart,
    pageEnd,
    hasPreviousPage,
    hasNextPage,
  } = ctl;

  return (
    <div ref={tableHostRef} className="relative">
      <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("queue.title")}
          </h2>
          {listQuery.isSuccess ? (
            <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
              {t("queue.showingRange", {
                start: pageStart,
                end: pageEnd,
                total: pageTotal,
              })}
            </p>
          ) : null}
        </div>

        {listQuery.isLoading ? (
          <LoadingState
            compact
            className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title={t("queue.loading")}
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
            title={t("queue.empty")}
          />
        ) : null}

        {listQuery.isSuccess && rows.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-sm">
                <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                  <tr className="text-start text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    <th className="px-4 py-3">{t("table.submitted")}</th>
                    <th className="px-4 py-3">{t("fields.rating")}</th>
                    <th className="px-4 py-3">{t("fields.category")}</th>
                    <th className="px-4 py-3 text-center">
                      {t("fields.status")}
                    </th>
                    <th className="px-4 py-3 text-center">
                      {t("fields.severity")}
                    </th>
                    <th className="px-4 py-3">{t("table.answerPreview")}</th>
                    <th className="px-4 py-3">{t("table.actions")}</th>
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
                            <span className="text-rose-700">
                              {t("ratings.down")}
                            </span>
                          ) : item.feedback?.rating === "up" ? (
                            <span className="text-emerald-700">
                              {t("ratings.up")}
                            </span>
                          ) : (
                            <span className="text-[#777587]">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-[#302f39] capitalize">
                          {categoryLabel(item.feedback?.category)}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span
                            className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${statusPillClass(item.status)}`}
                          >
                            {item.status === "new"
                              ? t("statusPills.new")
                              : t(
                                  `statuses.${({ needs_document_update: "needsDocumentUpdate", needs_prompt_retrieval_fix: "needsPromptRetrievalFix", converted_to_evaluation: "convertedToEvaluation", eval_created: "convertedToEvaluation", needs_document: "needsDocumentUpdate", fixed: "resolved" } as Record<string, string>)[item.status] ?? item.status}`,
                                )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span
                            className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${severityPillClass(item.severity)}`}
                          >
                            {t(`severities.${item.severity}`)}
                          </span>
                        </td>
                        <td className="max-w-[240px] px-4 py-3 text-xs text-[#464555]">
                          <span className="line-clamp-2">
                            {item.feedback?.question_text ??
                              item.message?.content_preview ??
                              "—"}
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
                            {t("actions.review")}
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
                {t("queue.showingItems", {
                  start: pageStart,
                  end: pageEnd,
                  total: pageTotal,
                })}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setOffset((p) => Math.max(0, p - PAGE_LIMIT))}
                  disabled={!hasPreviousPage || listQuery.isFetching}
                  className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("actions.previous")}
                </button>
                <button
                  type="button"
                  onClick={() => setOffset((p) => p + PAGE_LIMIT)}
                  disabled={!hasNextPage || listQuery.isFetching}
                  className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("actions.next")}
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
            aria-label={t("detail.closeReviewDetail")}
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
            onConvert={(reviewId) => setConvertReviewId(reviewId)}
            onSaveAsKnowledgeCard={(reviewId) =>
              setSaveKnowledgeCardReviewId(reviewId)
            }
            onRedact={(feedbackId) => redactMutation.mutate(feedbackId)}
            isUpdating={updateMutation.isPending}
          />
        </>
      ) : null}
    </div>
  );
}
