import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type {
  CriticWarningRecord,
  PlannerCriticRecord,
} from "@/lib/api/trust_metadata";

const STRATEGY_LABEL: Record<string, string> = {
  policy_lookup: "Policy lookup",
  comparison: "Comparison",
  legal_compliance: "Legal / compliance",
  table_heavy: "Table-heavy",
  graph_assisted: "Graph-assisted",
  connector_search: "Connector search",
  standard: "Standard",
};

const CRITIC_SEVERITY_COLOR: Record<string, string> = {
  none: "text-[#1a8a4a]",
  low: "text-[#b45309]",
  medium: "text-[#d97706]",
  high: "text-[#dc2626]",
};

const WARNING_SEVERITY_BADGE: Record<string, string> = {
  low: "inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold uppercase text-amber-700 border border-amber-200",
  medium:
    "inline-flex items-center rounded-full bg-orange-50 px-1.5 py-0.5 text-[9px] font-bold uppercase text-orange-700 border border-orange-200",
  high: "inline-flex items-center rounded-full bg-rose-50 px-1.5 py-0.5 text-[9px] font-bold uppercase text-rose-700 border border-rose-200",
};

export function PlannerCriticSection({
  plannerCritic,
}: {
  plannerCritic: PlannerCriticRecord | null;
}) {
  if (
    plannerCritic === null ||
    (plannerCritic.strategy === "standard" &&
      !plannerCritic.high_risk &&
      plannerCritic.critic_warnings.length === 0 &&
      !plannerCritic.refiner_applied)
  ) {
    return null;
  }

  const strategyLabel =
    STRATEGY_LABEL[plannerCritic.strategy] ?? plannerCritic.strategy;
  const severityColor =
    CRITIC_SEVERITY_COLOR[plannerCritic.critic_severity] ?? "text-[#464555]";

  return (
    <div className="space-y-2">
      <SectionHeader icon="auto_awesome" label="Answer Pipeline" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow label="Strategy" value={strategyLabel} />
        {plannerCritic.high_risk ? (
          <StatRow label="High-risk review" value="Yes" />
        ) : null}
        {plannerCritic.critic_severity !== "none" ? (
          <StatRow
            label="Critic severity"
            value={
              <span className={`font-semibold ${severityColor}`}>
                {plannerCritic.critic_severity}
              </span>
            }
          />
        ) : null}
        {plannerCritic.refiner_applied ? (
          <StatRow
            label="Refiner"
            value={
              plannerCritic.draft_changed
                ? "Applied — answer revised"
                : "Applied — no changes"
            }
          />
        ) : null}
        {plannerCritic.unsupported_claims_removed > 0 ? (
          <StatRow
            label="Claims removed"
            value={plannerCritic.unsupported_claims_removed}
          />
        ) : null}
      </div>

      {plannerCritic.critic_warnings.length > 0 ? (
        <div className="mt-1 space-y-1">
          <p className="text-[10px] font-semibold tracking-wide text-[#9896a8] uppercase">
            Critic warnings
          </p>
          <ul className="space-y-1">
            {plannerCritic.critic_warnings.map((w, i) => (
              <CriticWarningRow key={i} warning={w} />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function CriticWarningRow({ warning }: { warning: CriticWarningRecord }) {
  const badgeClass =
    WARNING_SEVERITY_BADGE[warning.severity] ?? WARNING_SEVERITY_BADGE.low;
  return (
    <li className="flex items-start gap-2 text-xs text-[#464555]">
      <span className="mt-0.5 shrink-0">
        <span className={badgeClass}>{warning.severity}</span>
      </span>
      <span>
        <span className="font-medium text-[#2d2c3e]">{warning.code}</span>
        {" — "}
        {warning.detail}
      </span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Retrieval method section (F341)
// ---------------------------------------------------------------------------
