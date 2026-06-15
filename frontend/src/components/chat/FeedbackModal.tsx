"use client";

import { useEffect, useRef, useState } from "react";
import type { FeedbackCategory, FeedbackReason } from "@/lib/api/feedback";

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

const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "wrong_citation", label: "Wrong or missing citation" },
  { value: "hallucination", label: "Unsupported or fabricated claim" },
  { value: "outdated_source", label: "Outdated source" },
  { value: "missing_document", label: "Relevant document not used" },
  { value: "unsafe_content", label: "Unsafe or sensitive content" },
  { value: "other", label: "Other" },
];

const CATEGORIES: { value: FeedbackCategory; label: string; description: string }[] = [
  { value: "wrong_answer", label: "Wrong answer", description: "The answer is factually incorrect" },
  { value: "bad_citation", label: "Bad citation", description: "Citation is wrong, missing, or irrelevant" },
  { value: "outdated_source", label: "Outdated source", description: "The source material is no longer current" },
  { value: "missing_information", label: "Missing information", description: "Relevant facts or context were omitted" },
  { value: "low_confidence", label: "Low confidence", description: "Answer feels uncertain or hedged without reason" },
  { value: "unsafe_response", label: "Unsafe response", description: "Answer contains harmful or sensitive content" },
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
  const overlayRef = useRef<HTMLDivElement>(null);
  const [reason, setReason] = useState<FeedbackReason | null>(
    existingReason ?? null,
  );
  const [category, setCategory] = useState<FeedbackCategory | null>(
    existingCategory ?? null,
  );
  const [comment, setComment] = useState(existingComment ?? "");

  const isEditing =
    existingReason != null || existingCategory != null || existingComment != null;
  const isBusy = isSubmitting || isDeleting;

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit(reason, comment.trim() || null, category);
  }

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label={isEditing ? "Edit feedback" : "Report an issue"}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <h2 className="text-base font-semibold text-[#2a2640]">
            {isEditing ? "Edit feedback" : "Report an issue"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff] hover:text-[#2f2a46]"
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
            <p className="mb-2 text-xs font-medium text-[#464555]">
              Issue type (optional)
            </p>
            <fieldset className="space-y-1">
              <legend className="sr-only">Feedback category</legend>
              {CATEGORIES.map(({ value, label, description }) => (
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
                    <span className="font-medium">{label}</span>
                    <span className="ml-1 text-[#777587]">— {description}</span>
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
                None of the above
              </label>
            </fieldset>
          </div>

          {/* Legacy reason — kept for backward compatibility */}
          <details className="rounded-lg border border-[#e2dff1]">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[#777587] hover:text-[#464555]">
              Additional classification (optional)
            </summary>
            <div className="px-3 pb-3">
              <fieldset className="space-y-1.5">
                <legend className="sr-only">Legacy reason</legend>
                {REASONS.map(({ value, label }) => (
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
                    {label}
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
                  None / prefer not to say
                </label>
              </fieldset>
            </div>
          </details>

          <div>
            <label
              htmlFor="feedback-comment"
              className="mb-1 block text-xs font-medium text-[#464555]"
            >
              Additional details (optional)
            </label>
            <textarea
              id="feedback-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="Describe the issue…"
              className="w-full resize-none rounded-lg border border-[#d7d4e8] bg-[#faf9ff] px-3 py-2 text-sm text-[#2a2640] placeholder-[#9d98b5] outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
            />
            <p className="mt-0.5 text-right text-[10px] text-[#9d98b5]">
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
                  className="text-xs text-rose-500 hover:underline disabled:opacity-50"
                >
                  {isDeleting ? "Removing…" : "Remove feedback"}
                </button>
              ) : null}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isBusy}
                className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-xs text-[#6a6780] hover:bg-[#f5f2ff] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isBusy}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#2a1eb5] disabled:opacity-50"
              >
                {isSubmitting ? "Submitting…" : "Submit"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
