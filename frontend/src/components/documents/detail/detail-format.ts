import type { DocumentStatus } from "@/lib/api/documents";

import type { TimelineStepState } from "@/components/documents/detail/detail-lifecycle";

const CHUNK_PAGE_SIZE = 8;
const CHUNK_PREVIEW_MAX_CHARS = 420;

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function truncateChunkPreview(value: string): string {
  if (value.length <= CHUNK_PREVIEW_MAX_CHARS) {
    return value;
  }
  return `${value.slice(0, CHUNK_PREVIEW_MAX_CHARS).trimEnd()}…`;
}

type NoChunksMessages = {
  processing: string;
  failed: string;
  deleting: string;
  default: string;
};

function noChunksMessage(
  status: DocumentStatus,
  messages: NoChunksMessages,
): string {
  if (status === "processing" || status === "uploaded") {
    return messages.processing;
  }
  if (status === "failed") {
    return messages.failed;
  }
  if (status === "deleting" || status === "deleted") {
    return messages.deleting;
  }
  return messages.default;
}

function documentTypeIcon(fileType: string): string {
  if (fileType === "pdf") {
    return "picture_as_pdf";
  }
  if (fileType === "docx") {
    return "description";
  }
  return "notes";
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function statusBadge(status: DocumentStatus): string {
  if (status === "indexed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "processing") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "uploaded") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "deleted") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function freshnessBadge(status: string | null | undefined): string {
  if (status === "trusted") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "current") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "needs_review") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function qualityBadge(status: string | null | undefined): string {
  if (status === "verified") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "reviewed") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "unreviewed") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "draft") {
    return "rounded-full bg-violet-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-violet-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deprecated") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function graphStatusBadge(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "pending" || status === "extracting") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function timelineStepClass(state: TimelineStepState): string {
  if (state === "completed") {
    return "border-[#3525cd] bg-[#3525cd] text-white";
  }
  if (state === "active") {
    return "border-[#4f46e5] bg-[#4f46e5] text-white";
  }
  if (state === "failed") {
    return "border-rose-300 bg-rose-100 text-rose-700";
  }
  return "border-[#d4d1df] bg-white text-[#777587]";
}

function timelineStepGlyph(state: TimelineStepState): string {
  if (state === "failed") {
    return "!";
  }
  if (state === "pending") {
    return "·";
  }
  return "✓";
}

export {
  CHUNK_PAGE_SIZE,
  documentTypeIcon,
  formatDate,
  freshnessBadge,
  graphStatusBadge,
  noChunksMessage,
  qualityBadge,
  statusBadge,
  timelineStepClass,
  timelineStepGlyph,
  triggerBlobDownload,
  truncateChunkPreview,
};
export type { NoChunksMessages };
