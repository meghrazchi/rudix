import { claimSupportBadge } from "@/components/chat/trust-panel/trust-badges";
import { pct } from "@/components/chat/trust-panel/trust-format";
import type { TrustPanelCitation } from "@/components/chat/trust-panel/trust-types";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatCitationResponse } from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

export function ClaimSupportSection({
  groundedVerification,
  trustCitations,
  onOpenCitation,
}: {
  groundedVerification:
    | AnswerTrustMetadataResponse["grounded_verification"]
    | null;
  trustCitations: TrustPanelCitation[];
  onOpenCitation: (citation: TrustPanelCitation) => void;
}) {
  const claimSupportRecords = groundedVerification?.claims ?? [];

  return (
    <>
      {groundedVerification && groundedVerification.claim_count > 0 && (
        <div className="space-y-2 px-4 pt-4 md:px-6 md:pt-5">
          <SectionHeader
            icon="fact_check"
            label={`Claim Support (${groundedVerification.supported_count}/${groundedVerification.claim_count})`}
          />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <StatRow
              label="Aggregate support"
              value={pct(groundedVerification.aggregate_support_score)}
            />
            <StatRow
              label="Verification score"
              value={pct(groundedVerification.score)}
            />
            <StatRow
              label="Supported claims"
              value={groundedVerification.supported_count}
            />
            <StatRow
              label="Partial claims"
              value={groundedVerification.partially_supported_count}
            />
            <StatRow
              label="Unsupported claims"
              value={groundedVerification.unsupported_count}
            />
            <StatRow
              label="Unverifiable claims"
              value={groundedVerification.unverifiable_count}
            />
          </div>
          <div className="space-y-1.5">
            {claimSupportRecords.length > 0 ? (
              claimSupportRecords.map((claim) => {
                const badge = claimSupportBadge(claim.support_status);
                const mappedCitations = claim.citation_indices
                  .map((index) => ({
                    index,
                    citation: trustCitations[index - 1],
                  }))
                  .filter(
                    (
                      item,
                    ): item is {
                      index: number;
                      citation: ChatCitationResponse;
                    } => Boolean(item.citation),
                  );
                return (
                  <div
                    key={`claim-${claim.claim_index}-${claim.claim_text}`}
                    className="rounded-lg border border-[#e2dff1] bg-white px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] leading-4 font-medium text-[#1b1b24]">
                          {claim.claim_text}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-1">
                          <span className={badge.cls}>{badge.label}</span>
                          <span className="text-[10px] text-[#9d98b5]">
                            Claim {claim.claim_index}
                          </span>
                          <span className="text-[10px] text-[#9d98b5]">
                            Support {pct(claim.support_score)}
                          </span>
                        </div>
                      </div>
                    </div>
                    {mappedCitations.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {mappedCitations.map(({ index, citation }) => {
                          const title =
                            citation.source_title ??
                            citation.filename ??
                            "Source";
                          return (
                            <button
                              type="button"
                              key={`${claim.claim_index}-${index}-${citation.document_id}-${citation.chunk_id}`}
                              onClick={() => onOpenCitation(citation)}
                              className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#3525cd] transition-colors hover:bg-[#ede9f9]"
                              aria-label={`Preview source ${index} for claim ${claim.claim_index}`}
                              title={title}
                            >
                              Source {index}
                              {citation.page_number
                                ? ` · p. ${citation.page_number}`
                                : ""}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-2 text-[10px] text-[#9d98b5]">
                        No validated citations mapped to this claim.
                      </p>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="rounded-lg border border-dashed border-[#d7d4e8] bg-white px-3 py-2 text-[11px] text-[#6a6780]">
                Claim-level citation mapping is not available for this answer
                snapshot.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
