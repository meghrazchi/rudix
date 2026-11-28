"use client";

import {
  type FeedbackReviewStatus,
  type FeedbackSeverity,
} from "@/lib/api/feedback-review";
import type { FeedbackCategory } from "@/lib/api/feedback";

export const PAGE_LIMIT = 20;

export type AppliedFilters = {
  status: FeedbackReviewStatus | null;
  category: FeedbackCategory | null;
  workspaceId: string | null;
  documentId: string | null;
  modelName: string | null;
  confidenceMin: string | null;
  confidenceMax: string | null;
  severity: FeedbackSeverity | null;
  rating: "up" | "down" | null;
  reason: string | null;
};

export const DEFAULT_FILTERS: AppliedFilters = {
  status: null,
  category: null,
  workspaceId: null,
  documentId: null,
  modelName: null,
  confidenceMin: null,
  confidenceMax: null,
  severity: null,
  rating: null,
  reason: null,
};

export function formatTimestamp(value: string): string {
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  return new Date(ts).toLocaleString();
}

export function statusPillClass(s: FeedbackReviewStatus): string {
  switch (s) {
    case "resolved":
    case "fixed":
      return "bg-emerald-100 text-emerald-800";
    case "converted_to_evaluation":
    case "eval_created":
      return "bg-emerald-100 text-emerald-800";
    case "rejected":
    case "duplicate":
      return "bg-slate-200 text-slate-700";
    case "accepted":
      return "bg-violet-100 text-violet-800";
    case "needs_document_update":
    case "needs_document":
    case "needs_prompt_retrieval_fix":
      return "bg-amber-100 text-amber-800";
    case "triaged":
      return "bg-blue-100 text-blue-800";
    default:
      return "bg-rose-100 text-rose-800";
  }
}

export function severityPillClass(s: FeedbackSeverity): string {
  switch (s) {
    case "high":
      return "bg-rose-100 text-rose-800";
    case "medium":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

export function categoryLabel(cat: string | null | undefined): string {
  if (!cat) return "—";
  return cat.replace(/_/g, " ");
}

export function trimToNull(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function parseNullableNumber(
  value: string | null | undefined,
): number | null {
  const trimmed = trimToNull(value);
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function triggerCsvDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "feedback-review-queue.csv";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
