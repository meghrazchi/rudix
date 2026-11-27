import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";

export function PolicySection({
  policyOutcome,
  policyViolatedRules,
  policyWarningFlags,
}: {
  policyOutcome: string | null;
  policyViolatedRules: string[];
  policyWarningFlags: string[];
}) {
  return (
    <div className="space-y-2">
      <SectionHeader icon="policy" label="Policy" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {policyOutcome ? (
          <StatRow label="Outcome" value={policyOutcome} />
        ) : null}
        {policyViolatedRules.length > 0 ? (
          <StatRow
            label="Violated rules"
            value={policyViolatedRules.join(", ")}
          />
        ) : null}
        {policyWarningFlags.length > 0 ? (
          <StatRow label="Warnings" value={policyWarningFlags.join(", ")} />
        ) : null}
      </div>
    </div>
  );
}
