"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { getApiErrorMessage } from "@/lib/api/errors";
import { listEvaluationSets } from "@/lib/api/evaluations";
import { convertFeedbackToEvalCase } from "@/lib/api/feedback-review";
import { queryKeys } from "@/lib/api/query";
import { trimToNull } from "@/components/admin/feedback-review/feedbackReviewShared";

export type ConvertModalProps = {
  reviewId: string;
  onClose: () => void;
  onConverted: (reviewId: string) => void;
};

export function ConvertToEvalModal({
  reviewId,
  onClose,
  onConverted,
}: ConvertModalProps) {
  const t = useTranslations("adminFeedbackReview");
  const [evalSetId, setEvalSetId] = useState("");
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">(
    "medium",
  );
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const evalSetsQuery = useQuery({
    queryKey: queryKeys.evaluationSetsList,
    queryFn: () => listEvaluationSets({ limit: 100, offset: 0 }),
  });

  const convertMutation = useMutation({
    mutationFn: () =>
      convertFeedbackToEvalCase(reviewId, {
        evaluation_set_id: evalSetId,
        default_difficulty: difficulty,
        reviewer_notes: trimToNull(notes),
      }),
    onSuccess: () => {
      onConverted(reviewId);
      onClose();
    },
    onError: (err) => {
      setError(getApiErrorMessage(err));
    },
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("convert.title")}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.currentTarget === e.target) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <h2 className="text-base font-semibold text-[#2a2640]">
            {t("convert.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("actions.close")}
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff]"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <label className="block space-y-1">
            <span className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              {t("convert.dataset")}
            </span>
            {evalSetsQuery.isLoading ? (
              <p className="text-sm text-[#777587]">
                {t("convert.loadingDatasets")}
              </p>
            ) : (
              <select
                value={evalSetId}
                onChange={(e) => setEvalSetId(e.target.value)}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="">{t("convert.selectDataset")}</option>
                {evalSetsQuery.data?.items.map((s) => (
                  <option key={s.evaluation_set_id} value={s.evaluation_set_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              {t("convert.difficulty")}
            </span>
            <select
              value={difficulty}
              onChange={(e) =>
                setDifficulty(e.target.value as "easy" | "medium" | "hard")
              }
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="easy">{t("difficulty.easy")}</option>
              <option value="medium">{t("difficulty.medium")}</option>
              <option value="hard">{t("difficulty.hard")}</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              {t("convert.reviewerNotesOptional")}
            </span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              maxLength={4000}
              className="w-full resize-none rounded-lg border border-[#c7c4d8] bg-white px-3 py-2 text-sm text-[#1b1b24]"
            />
          </label>

          {error ? <p className="text-sm text-rose-700">{error}</p> : null}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={convertMutation.isPending}
              className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-xs text-[#6a6780] hover:bg-[#f5f2ff] disabled:opacity-50"
            >
              {t("actions.cancel")}
            </button>
            <button
              type="button"
              onClick={() => convertMutation.mutate()}
              disabled={!evalSetId || convertMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#2a1eb5] disabled:opacity-50"
            >
              {convertMutation.isPending
                ? t("convert.converting")
                : t("actions.convert")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
