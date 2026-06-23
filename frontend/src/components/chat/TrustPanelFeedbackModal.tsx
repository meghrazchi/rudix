"use client";

import { useRef, useState } from "react";

import type { FeedbackCategory } from "@/lib/api/feedback";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

export type TrustPanelCitationRef = {
  document_id: string;
  chunk_id: string;
  title: string;
};

export type TrustPanelFeedbackPayload = {
  category: FeedbackCategory | null;
  comment: string | null;
  selectedCitationIds: string[];
  traceId: string | null;
  trustScore: number | null;
  trustLevel: string | null;
};

type Props = {
  /** Warnings active in the trust panel — used to suggest a category. */
  activeWarnings: string[];
  citations: TrustPanelCitationRef[];
  traceId: string | null;
  trustScore: number | null;
  trustLevel: string | null;
  isSubmitting: boolean;
  onSubmit: (payload: TrustPanelFeedbackPayload) => void;
  onClose: () => void;
};

const TRUST_PANEL_CATEGORIES: {
  value: FeedbackCategory;
  label: string;
  description: string;
  warningKeywords: string[];
}[] = [
  {
    value: "wrong_answer",
    label: "Wrong answer",
    description: "The answer is factually incorrect",
    warningKeywords: ["verification failed", "unsupported", "hallucin"],
  },
  {
    value: "bad_citation",
    label: "Bad citation",
    description: "A citation is wrong, irrelevant, or points to the wrong place",
    warningKeywords: ["citation validation failed"],
  },
  {
    value: "missing_citation",
    label: "Missing citation",
    description: "A citation that should be there is absent",
    warningKeywords: [],
  },
  {
    value: "stale_source",
    label: "Stale source",
    description: "The cited source is outdated or no longer accurate",
    warningKeywords: ["stale", "expired", "outdated", "deprecated", "unreviewed"],
  },
  {
    value: "conflicting_source",
    label: "Conflicting source",
    description: "Cited sources disagree with each other",
    warningKeywords: ["conflict", "disagree"],
  },
  {
    value: "not_enough_detail",
    label: "Not enough detail",
    description: "The answer is too vague or incomplete",
    warningKeywords: ["low confidence", "weak"],
  },
  {
    value: "should_have_said_not_found",
    label: "Should have said not found",
    description: "No relevant information exists — the model should have said so",
    warningKeywords: ["not_found", "no context"],
  },
];

function inferCategory(warnings: string[]): FeedbackCategory | null {
  const lc = warnings.map((w) => w.toLowerCase()).join(" ");
  for (const cat of TRUST_PANEL_CATEGORIES) {
    if (cat.warningKeywords.some((kw) => lc.includes(kw))) {
      return cat.value;
    }
  }
  return null;
}

export function TrustPanelFeedbackModal({
  activeWarnings,
  citations,
  traceId,
  trustScore,
  trustLevel,
  isSubmitting,
  onSubmit,
  onClose,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  const [category, setCategory] = useState<FeedbackCategory | null>(
    () => inferCategory(activeWarnings),
  );
  const [selectedCitationIds, setSelectedCitationIds] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  useOverlayFocus({
    isOpen: true,
    containerRef: dialogRef,
    onClose,
    autofocusSelector: "[data-overlay-autofocus='true']",
  });

  function toggleCitation(docId: string) {
    setSelectedCitationIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId],
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      category,
      comment: comment.trim() || null,
      selectedCitationIds,
      traceId,
      trustScore,
      trustLevel,
    });
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
        aria-labelledby="trust-feedback-modal-title"
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <div className="flex items-center gap-2">
            <span
              className="material-symbols-outlined text-[16px] text-rose-500"
              aria-hidden="true"
            >
              flag
            </span>
            <h2
              id="trust-feedback-modal-title"
              className="text-base font-semibold text-[#2a2640]"
            >
              Report answer issue
            </h2>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            aria-label="Close report dialog"
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff] hover:text-[#2f2a46] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
              close
            </span>
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          {/* Category picker */}
          <div>
            <p
              id="trust-feedback-category-label"
              className="mb-2 text-xs font-medium text-[#464555]"
            >
              What is wrong with this answer?
            </p>
            <fieldset aria-labelledby="trust-feedback-category-label" className="space-y-1">
              <legend className="sr-only">Issue category</legend>
              {TRUST_PANEL_CATEGORIES.map(({ value, label, description }) => (
                <label
                  key={value}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg px-3 py-2 text-sm text-[#2a2640] hover:bg-[#f5f2ff]"
                >
                  <input
                    type="radio"
                    name="trust-category"
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
                  name="trust-category"
                  value=""
                  checked={category === null}
                  onChange={() => setCategory(null)}
                  className="accent-[#3525cd]"
                />
                Other / not listed
              </label>
            </fieldset>
          </div>

          {/* Citation selection */}
          {citations.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-[#464555]">
                Flag specific sources (optional)
              </p>
              <div className="max-h-36 space-y-1 overflow-y-auto rounded-lg border border-[#e2dff1] bg-[#faf9ff] p-2">
                {citations.map((cit) => (
                  <label
                    key={`${cit.document_id}:${cit.chunk_id}`}
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-xs text-[#2a2640] hover:bg-[#f0eeff]"
                  >
                    <input
                      type="checkbox"
                      checked={selectedCitationIds.includes(cit.document_id)}
                      onChange={() => toggleCitation(cit.document_id)}
                      className="accent-[#3525cd]"
                    />
                    <span className="truncate">{cit.title}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Comment */}
          <div>
            <label
              htmlFor="trust-feedback-comment"
              className="mb-1 block text-xs font-medium text-[#464555]"
            >
              Additional details (optional)
            </label>
            <textarea
              id="trust-feedback-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="Describe what was wrong…"
              aria-describedby="trust-feedback-comment-count"
              className="w-full resize-none rounded-lg border border-[#d7d4e8] bg-[#faf9ff] px-3 py-2 text-sm text-[#2a2640] placeholder-[#9d98b5] outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
            />
            <p
              id="trust-feedback-comment-count"
              aria-live="polite"
              aria-atomic="true"
              className="mt-0.5 text-right text-[10px] text-[#9d98b5]"
            >
              {comment.length}/1000
            </p>
          </div>

          {/* Trace context badge */}
          {traceId && (
            <p className="text-[10px] text-[#9d98b5]">
              Trace ID:{" "}
              <span className="font-mono">{traceId}</span>
            </p>
          )}

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-xs text-[#6a6780] hover:bg-[#f5f2ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-rose-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-600 focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-50"
            >
              {isSubmitting ? "Reporting…" : "Report issue"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
