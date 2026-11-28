import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat.trustPanel");
  return (
    <div className="space-y-2">
      <SectionHeader icon="hub" label={t("graph.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {debug?.graph_context_unavailable ? (
          <div className="col-span-2">
            <p className="text-[11px] text-[#9d98b5]">
              {debug.graph_context_reason ?? t("graph.unavailable")}
            </p>
          </div>
        ) : (
          <>
            <StatRow
              label={t("graph.seedEntities")}
              value={debug?.graph_seed_entity_count ?? 0}
            />
            <StatRow
              label={t("graph.relatedEntities")}
              value={debug?.graph_related_entity_count ?? 0}
            />
            <StatRow
              label={t("graph.chunks")}
              value={debug?.graph_chunk_count ?? 0}
            />
            <StatRow
              label={t("graph.maxHops")}
              value={debug?.graph_max_hops_used ?? null}
            />
            {(debug?.graph_relation_types_used?.length ?? 0) > 0 ? (
              <StatRow
                label={t("graph.relationTypes")}
                value={debug!.graph_relation_types_used!.join(", ")}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
