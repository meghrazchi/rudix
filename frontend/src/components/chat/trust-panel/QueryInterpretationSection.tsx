import { queryComplexityLabel } from "@/components/chat/trust-panel/trust-format";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { QueryInterpretationRecord } from "@/lib/api/trust_metadata";

export function QueryInterpretationSection({
  queryInterpretation,
}: {
  queryInterpretation: QueryInterpretationRecord;
}) {
  return (
    <div className="space-y-2">
      <SectionHeader icon="manage_search" label="Query Interpretation" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow label="Intent" value={queryInterpretation.intent_label} />
        <StatRow
          label="Strategy"
          value={queryInterpretation.retrieval_strategy}
        />
        <StatRow
          label="Complexity"
          value={queryComplexityLabel(queryInterpretation.complexity)}
        />
      </div>
      {queryInterpretation.rewrite_preview_enabled ? (
        <div className="space-y-2">
          {queryInterpretation.rewritten_query_preview ? (
            <div className="rounded-lg border border-[#e2dff1] bg-white px-3 py-2">
              <p className="text-[10px] font-semibold tracking-widest text-[#6a6780] uppercase">
                Rewrite preview
              </p>
              <p className="mt-1 text-[11px] leading-snug text-[#2f2a46]">
                {queryInterpretation.rewritten_query_preview}
              </p>
            </div>
          ) : null}
          {queryInterpretation.sub_queries.length > 0 ? (
            <div className="space-y-1 rounded-lg border border-[#e2dff1] bg-white px-3 py-2">
              <p className="text-[10px] font-semibold tracking-widest text-[#6a6780] uppercase">
                Sub-queries
              </p>
              <div className="space-y-1">
                {queryInterpretation.sub_queries.map((subQuery, index) => (
                  <div
                    key={`${queryInterpretation.retrieval_strategy}-${index}-${subQuery}`}
                    className="rounded-md bg-[#faf9ff] px-2 py-1 text-[11px] leading-snug text-[#2f2a46]"
                  >
                    {subQuery}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-[11px] text-[#6a6780]">
          Rewrite preview is disabled by organization policy.
        </p>
      )}
    </div>
  );
}
