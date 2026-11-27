import type { ChatDebugResponse } from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

export type RetrievalDiagnostics =
  | AnswerTrustMetadataResponse["retrieval"]
  | ChatDebugResponse
  | null;

export function SourceSelectionSection({
  retrievalSummary,
  retrievalDiagnostics,
}: {
  retrievalSummary: string | null;
  retrievalDiagnostics: RetrievalDiagnostics;
}) {
  return (
    <>
      {retrievalSummary ? (
        <div className="space-y-2 px-4 pt-4 md:px-6 md:pt-5">
          <p className="text-[10px] font-semibold tracking-widest text-[#6a6780] uppercase">
            Source selection
          </p>
          <p className="text-[11px] leading-snug text-[#2f2a46]">
            {retrievalSummary}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {retrievalDiagnostics?.request_id ? (
              <span className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#3525cd]">
                Request {retrievalDiagnostics.request_id}
              </span>
            ) : null}
            {retrievalDiagnostics?.trace_request_id &&
            retrievalDiagnostics.trace_request_id !==
              retrievalDiagnostics.request_id ? (
              <span className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#3525cd]">
                Trace {retrievalDiagnostics.trace_request_id}
              </span>
            ) : null}
            {retrievalDiagnostics?.search_mode ? (
              <span className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#3525cd]">
                Mode {retrievalDiagnostics.search_mode}
              </span>
            ) : null}
            {retrievalDiagnostics?.rerank_fallback_used ? (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-800">
                Rerank fallback
              </span>
            ) : retrievalDiagnostics?.rerank_applied ? (
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
                Rerank on
              </span>
            ) : (
              <span className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#6a6780]">
                Rerank off
              </span>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
