import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatDebugResponse } from "@/lib/api/chat";

export function GraphRagSection({
  debug,
}: {
  debug: ChatDebugResponse | null;
}) {
  return (
    <div className="space-y-2">
      <SectionHeader icon="hub" label="Knowledge Graph" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {debug?.graph_context_unavailable ? (
          <div className="col-span-2">
            <p className="text-[11px] text-[#9d98b5]">
              {debug.graph_context_reason ?? "Graph context unavailable."}
            </p>
          </div>
        ) : (
          <>
            <StatRow
              label="Seed entities"
              value={debug?.graph_seed_entity_count ?? 0}
            />
            <StatRow
              label="Related entities"
              value={debug?.graph_related_entity_count ?? 0}
            />
            <StatRow
              label="Graph chunks"
              value={debug?.graph_chunk_count ?? 0}
            />
            <StatRow
              label="Max hops"
              value={debug?.graph_max_hops_used ?? null}
            />
            {(debug?.graph_relation_types_used?.length ?? 0) > 0 ? (
              <StatRow
                label="Relation types"
                value={debug!.graph_relation_types_used!.join(", ")}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
