import {
  agreementLevelClass,
  agreementLevelLabel,
} from "@/components/chat/ConflictIndicators";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ConflictStatusRecord } from "@/lib/api/trust_metadata";

function SourceConflictSection({
  conflict,
}: {
  conflict: ConflictStatusRecord;
}) {
  return (
    <div className="space-y-2" data-testid="source-conflict-section">
      <SectionHeader icon="warning" label="Source Conflict" />
      <div className="flex flex-wrap items-center gap-2">
        <span className={agreementLevelClass(conflict.agreement_level)}>
          {agreementLevelLabel(conflict.agreement_level)}
        </span>
        {conflict.conflict_count > 0 && (
          <span className="text-[11px] text-[#6a6780]">
            {conflict.conflict_count} conflict pair
            {conflict.conflict_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {conflict.conflict_summary ? (
        <p className="text-[11px] leading-snug text-[#6a6780]">
          {conflict.conflict_summary}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {conflict.conflicting_document_ids.length > 0 && (
          <StatRow
            label="Sources in conflict"
            value={conflict.conflicting_document_ids.length}
          />
        )}
        {conflict.preferred_document_ids.length > 0 && (
          <StatRow
            label="Preferred source count"
            value={conflict.preferred_document_ids.length}
          />
        )}
        {conflict.preferred_document_ids.length === 0 && conflict.detected && (
          <div className="col-span-2 text-[11px] text-[#9d98b5]">
            No preferred source could be determined — treat all sources with
            equal caution.
          </div>
        )}
      </div>
    </div>
  );
}

export function ConflictSection({
  conflictRecord,
}: {
  conflictRecord: ConflictStatusRecord | null;
}) {
  return (
    <>
      {conflictRecord && conflictRecord.agreement_level !== "full" && (
        <div className="px-4 pt-4 md:px-6 md:pt-5">
          <SourceConflictSection conflict={conflictRecord} />
        </div>
      )}
    </>
  );
}
