"use client";

import type { VerifiedAnswerStatus } from "@/lib/api/verified-answers";

const STATUS_CONFIG: Record<
  VerifiedAnswerStatus,
  { label: string; color: string; bg: string }
> = {
  draft: {
    label: "Draft",
    color: "text-gray-600",
    bg: "bg-gray-100",
  },
  pending_review: {
    label: "Pending review",
    color: "text-amber-700",
    bg: "bg-amber-50 border border-amber-200",
  },
  approved: {
    label: "Approved",
    color: "text-blue-700",
    bg: "bg-blue-50 border border-blue-200",
  },
  published: {
    label: "Verified",
    color: "text-emerald-700",
    bg: "bg-emerald-50 border border-emerald-200",
  },
  archived: {
    label: "Archived",
    color: "text-gray-500",
    bg: "bg-gray-100",
  },
};

type Props = {
  status: VerifiedAnswerStatus;
  isStale?: boolean;
  className?: string;
};

export function VerifiedAnswerBadge({
  status,
  isStale,
  className = "",
}: Props) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${config.bg} ${config.color} ${className}`}
    >
      {status === "published" && <span aria-hidden="true">✓</span>}
      {config.label}
      {isStale && (
        <span
          className="ml-0.5 text-amber-600"
          title="This card may be outdated"
        >
          ⚠
        </span>
      )}
    </span>
  );
}
