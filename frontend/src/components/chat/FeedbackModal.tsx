"use client";

import { useRef, useState } from "react";

import { useTranslations } from "next-intl";
import type { FeedbackCategory, FeedbackReason } from "@/lib/api/feedback";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

type Props = {
  existingReason: FeedbackReason | null | undefined;
  existingCategory: FeedbackCategory | null | undefined;
  existingComment: string | null | undefined;
  isSubmitting: boolean;
  isDeleting: boolean;
  onSubmit: (
    reason: FeedbackReason | null,
    comment: string | null,
    category: FeedbackCategory | null,
  ) => void;
  onDelete: () => void;
  onClose: () => void;
};

const REASONS: FeedbackReason[] = [
  "wrong_citation",
  "hallucination",
  "outdated_source",
  "missing_document",
  "unsafe_content",
  "other",
];

const CATEGORIES: FeedbackCategory[] = [
  "wrong_answer",
  "bad_citation",
  "missing_citation",
  "missing_source",
  "outdated_source",
  "hallucination_risk",
  "conflict_not_detected",
  "unclear_answer",
  "should_have_said_not_found",
];

export function FeedbackModal({
  existingReason,
  existingCategory,
  existingComment,
  isSubmitting,
  isDeleting,
  onSubmit,
  onDelete,
  onClose,
}: Props) {
  const t = useTranslations("chat.feedback");
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [reason, setReason] = useState<FeedbackReason | null>(
    existingReason ?? null,
  );
  const [category, setCategory] = useState<FeedbackCategory | null>(
    existingCategory ?? null,
  );
  const [comment, setComment] = useState(existingComment ?? "");

  const isEditing =
    existingReason != null ||
    existingCategory != null ||
    existingComment != null;
  const isBusy = isSubmitting || isDeleting;

  useOverlayFocus({
    isOpen: true,
    containerRef: dialogRef,
    onClose,
    autofocusSelector: "[data-overlay-autofocus='true']",
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit(reason, comment.trim() || null, category);
  }

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-modal-title"
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <h2
            id="feedback-modal-title"
            className="text-base font-semibold text-[#2a2640]"
          >
            {isEditing ? t("title.edit") : t("title.new")}
          </h2>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            aria-label={t("closeAria")}
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff] hover:text-[#2f2a46] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          {/* Structured category — F303 */}
          <div>
            <p
              id="feedback-category-label"
              className="mb-2 text-xs font-medium text-[#464555]"
            >
              {t("issueType")}
            </p>
            <fieldset
              aria-labelledby="feedback-category-label"
              className="space-y-1"
            >
              <legend className="sr-only">{t("categoryLegend")}</legend>
              {CATEGORIES.map((value) => (
                <label
                  key={value}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg px-3 py-2 text-sm text-[#2a2640] hover:bg-[#f5f2ff]"
                >
                  <input
                    type="radio"
                    name="category"
                    value={value}
                    checked={category === value}
                    onChange={() => setCategory(value)}
                    className="mt-0.5 accent-[#3525cd]"
                  />
                  <span>
                    <span className="font-medium">
                      {t(`categoryLabels.${value}`)}
                    </span>
                    <span className="ml-1 text-[#777587]">
                      — {t(`categoryDescriptions.${value}`)}
                    </span>
                  </span>
                </label>
              ))}
              <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[#6a6780] hover:bg-[#f5f2ff]">
                <input
                  type="radio"
                  name="category"
                  value=""
                  checked={category === null}
                  onChange={() => setCategory(null)}
                  className="accent-[#3525cd]"
                />
                {t("noneOfAbove")}
              </label>
            </fieldset>
          </div>

          {/* Legacy reason — kept for backward compatibility */}
          <details className="rounded-lg border border-[#e2dff1]">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[#777587] hover:text-[#464555]">
              {t("additionalClassification")}
            </summary>
            <div className="px-3 pb-3">
              <fieldset className="space-y-1.5">
                <legend className="sr-only">{t("legacyLegend")}</legend>
                {REASONS.map((value) => (
                  <label
                    key={value}
                    className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-[#2a2640] hover:bg-[#f5f2ff]"
                  >
                    <input
                      type="radio"
                      name="reason"
                      value={value}
                      checked={reason === value}
                      onChange={() => setReason(value)}
                      className="accent-[#3525cd]"
                    />
                    {t(`reasons.${value}`)}
                  </label>
                ))}
                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-[#6a6780] hover:bg-[#f5f2ff]">
                  <input
                    type="radio"
                    name="reason"
                    value=""
                    checked={reason === null}
                    onChange={() => setReason(null)}
                    className="accent-[#3525cd]"
                  />
                  {t("noneSkip")}
                </label>
              </fieldset>
            </div>
          </details>

          <div>
            <label
              htmlFor="feedback-comment"
              className="mb-1 block text-xs font-medium text-[#464555]"
            >
              {t("details")}
            </label>
            <textarea
              id="feedback-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder={t("placeholder")}
              aria-describedby="feedback-comment-count"
              className="w-full resize-none rounded-lg border border-[#d7d4e8] bg-[#faf9ff] px-3 py-2 text-sm text-[#2a2640] placeholder-[#9d98b5] outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
            />
            <p
              id="feedback-comment-count"
              aria-live="polite"
              aria-atomic="true"
              className="mt-0.5 text-right text-[10px] text-[#9d98b5]"
            >
              {comment.length}/1000
            </p>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between gap-2 pt-1">
            <div>
              {isEditing ? (
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={isBusy}
                  className="text-xs text-rose-500 hover:underline focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:outline-none disabled:opacity-50"
                >
                  {isDeleting ? t("removing") : t("remove")}
                </button>
              ) : null}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isBusy}
                className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-xs text-[#6a6780] hover:bg-[#f5f2ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:opacity-50"
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                disabled={isBusy}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#2a1eb5] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-50"
              >
                {isSubmitting ? t("submitting") : t("submit")}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
