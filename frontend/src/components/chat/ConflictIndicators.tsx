"use client";

import type { ChatCitationResponse } from "@/lib/api/chat";

export function agreementLevelLabel(
  level: "full" | "partial" | "conflicting",
): string {
  if (level === "partial") {
    return "Partial agreement";
  }
  if (level === "conflicting") {
    return "Conflicting sources";
  }
  return "Full agreement";
}

export function agreementLevelClass(
  level: "full" | "partial" | "conflicting",
): string {
  if (level === "conflicting") {
    return "inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-rose-800";
  }
  if (level === "partial") {
    return "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-800";
  }
  return "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-800";
}

function conflictStatusLabel(
  status: "preferred" | "conflicting" | "neutral" | null | undefined,
): string | null {
  if (status === "preferred") {
    return "Preferred";
  }
  if (status === "conflicting") {
    return "Conflicting";
  }
  return null;
}

export function ConflictWarningCard({
  conflictDetected,
  agreementLevel,
  conflictSummary,
  preferredDocumentIds,
}: {
  conflictDetected: boolean;
  agreementLevel: "full" | "partial" | "conflicting";
  conflictSummary: string | null;
  preferredDocumentIds: string[];
}) {
  if (!conflictDetected) {
    return null;
  }

  return (
    <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-900">
      <div className="flex flex-wrap items-center gap-2">
        <span className={agreementLevelClass(agreementLevel)}>
          {agreementLevelLabel(agreementLevel)}
        </span>
        <span className="font-semibold">Source conflict detected</span>
      </div>
      {conflictSummary ? (
        <p className="mt-1 text-[11px] leading-snug">{conflictSummary}</p>
      ) : null}
      {preferredDocumentIds.length > 0 ? (
        <p className="mt-1 text-[11px] leading-snug">
          Preferred source IDs: {preferredDocumentIds.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

export function ConflictSourceComparison({
  conflictDetected,
  agreementLevel,
  conflictSummary,
  preferredDocumentIds,
  citations,
}: {
  conflictDetected: boolean;
  agreementLevel: "full" | "partial" | "conflicting";
  conflictSummary: string | null;
  preferredDocumentIds: string[];
  citations: ChatCitationResponse[];
}) {
  if (!conflictDetected) {
    return null;
  }

  return (
    <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
      <div className="flex flex-wrap items-center gap-2">
        <span className={agreementLevelClass(agreementLevel)}>
          {agreementLevelLabel(agreementLevel)}
        </span>
        <span className="font-semibold">Source comparison</span>
      </div>
      {conflictSummary ? (
        <p className="mt-1 text-[11px] leading-snug">{conflictSummary}</p>
      ) : null}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-2 text-[10px] font-bold tracking-widest text-emerald-800 uppercase">
            Preferred sources
          </p>
          <div className="space-y-2">
            {citations
              .filter((citation) =>
                preferredDocumentIds.includes(citation.document_id),
              )
              .map((citation, index) => (
                <div
                  key={`preferred:${citation.document_id}:${citation.chunk_id}:${index}`}
                  className="rounded-lg border border-emerald-200 bg-white p-3"
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] font-bold text-emerald-700 uppercase">
                      {citation.filename ?? "Document"}
                    </span>
                    <span className="text-[9px] font-semibold text-emerald-700 uppercase">
                      Preferred
                    </span>
                  </div>
                  <p className="text-[11px] leading-snug text-rose-900">
                    {citation.text_snippet ?? "No snippet available."}
                  </p>
                </div>
              ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-[10px] font-bold tracking-widest text-rose-800 uppercase">
            Conflicting sources
          </p>
          <div className="space-y-2">
            {citations
              .filter((citation) => citation.conflict_status === "conflicting")
              .map((citation, index) => (
                <div
                  key={`conflicting:${citation.document_id}:${citation.chunk_id}:${index}`}
                  className="rounded-lg border border-rose-200 bg-white p-3"
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] font-bold text-rose-700 uppercase">
                      {citation.filename ?? "Document"}
                    </span>
                    <span className="text-[9px] font-semibold text-rose-700 uppercase">
                      {conflictStatusLabel(citation.conflict_status)}
                    </span>
                  </div>
                  <p className="text-[11px] leading-snug text-rose-900">
                    {citation.text_snippet ?? "No snippet available."}
                  </p>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}
