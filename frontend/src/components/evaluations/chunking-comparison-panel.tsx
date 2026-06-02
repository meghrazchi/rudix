import {
  formatInteger,
  formatPercent,
} from "@/components/evaluations/evaluation-view-model";

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function summaryDimensionEntries(
  value: unknown,
): Array<[string, Record<string, unknown>]> {
  const record = asRecord(value);
  if (!record) {
    return [];
  }
  return Object.entries(record)
    .map(([label, entry]) => [label, asRecord(entry)] as const)
    .filter(
      (entry): entry is [string, Record<string, unknown>] => entry[1] != null,
    );
}

export function ChunkingComparisonPanel({
  summaryValue,
}: {
  summaryValue: unknown;
}) {
  const summary = asRecord(summaryValue);
  const targets = asRecordArray(summary?.comparison_targets);
  if (targets.length === 0) {
    return null;
  }

  const bestByDocumentType = summaryDimensionEntries(
    summary?.best_by_document_type,
  );
  const bestByUseCase = summaryDimensionEntries(summary?.best_by_use_case);

  return (
    <section className="space-y-3 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[#2f2a48]">
            Chunking strategy comparison
          </h3>
          <p className="mt-1 text-xs text-[#6a6581]">
            Question-level results below reflect the primary target. This panel
            compares all configured profiles on the same evaluation set.
          </p>
        </div>
        <span className="rounded-full border border-[#d7d2e8] bg-white px-2 py-1 text-xs font-semibold text-[#4d4668]">
          {targets.length} target{targets.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-[#e7e3f3] bg-white">
        <table className="min-w-full divide-y divide-[#ece8f6] text-sm">
          <thead className="bg-[#f7f5fd] text-left text-xs font-semibold tracking-wide text-[#665f81] uppercase">
            <tr>
              <th className="px-3 py-2">Profile</th>
              <th className="px-3 py-2">Strategy</th>
              <th className="px-3 py-2">Score</th>
              <th className="px-3 py-2">Retrieval</th>
              <th className="px-3 py-2">Citation</th>
              <th className="px-3 py-2">Faithfulness</th>
              <th className="px-3 py-2">Chunks</th>
              <th className="px-3 py-2">Avg tokens</th>
              <th className="px-3 py-2">Not found</th>
              <th className="px-3 py-2">Regression</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f0edf7]">
            {targets.map((target, index) => {
              const regressionFlags = asRecordArray(target.regression_flags);
              return (
                <tr key={`${asString(target.label) ?? "target"}-${index + 1}`}>
                  <td className="px-3 py-2 align-top text-[#2f2a48]">
                    <div className="font-semibold">
                      {asString(target.label) ?? `Target ${index + 1}`}
                    </div>
                    <div className="text-xs text-[#6a6581]">
                      {asString(target.profile_version) ??
                        "Version unavailable"}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {asString(target.chunking_strategy) ?? "Unknown"}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatPercent(asNumber(target.overall_score))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatPercent(asNumber(target.retrieval_hit_rate))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatPercent(asNumber(target.citation_accuracy_score))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatPercent(asNumber(target.faithfulness_score))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatInteger(asNumber(target.chunk_count_total))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatInteger(asNumber(target.chunk_tokens_average))}
                  </td>
                  <td className="px-3 py-2 align-top text-[#4b4564]">
                    {formatPercent(asNumber(target.not_found_rate))}
                  </td>
                  <td className="px-3 py-2 align-top">
                    {regressionFlags.length === 0 ? (
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        Clear
                      </span>
                    ) : (
                      <div className="space-y-1">
                        {regressionFlags.map((flag, flagIndex) => (
                          <div
                            key={`${asString(flag.metric) ?? "flag"}-${flagIndex + 1}`}
                            className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-900"
                          >
                            {asString(flag.metric) ?? "metric"}:{" "}
                            {formatPercent(asNumber(flag.value))}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {bestByDocumentType.length > 0 || bestByUseCase.length > 0 ? (
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-[#e7e3f3] bg-white p-3">
            <h4 className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
              Best by document type
            </h4>
            {bestByDocumentType.length === 0 ? (
              <p className="mt-2 text-xs text-[#6a6581]">
                No document-type breakdown available.
              </p>
            ) : (
              <ul className="mt-2 space-y-2 text-sm text-[#403b5b]">
                {bestByDocumentType.map(([label, entry]) => (
                  <li
                    key={`doc-type-${label}`}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="font-medium">{label}</span>
                    <span className="text-right text-xs text-[#6a6581]">
                      {asString(entry.label) ?? "Unknown"} •{" "}
                      {formatPercent(asNumber(entry.score))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-lg border border-[#e7e3f3] bg-white p-3">
            <h4 className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
              Best by use case
            </h4>
            {bestByUseCase.length === 0 ? (
              <p className="mt-2 text-xs text-[#6a6581]">
                No use-case breakdown available.
              </p>
            ) : (
              <ul className="mt-2 space-y-2 text-sm text-[#403b5b]">
                {bestByUseCase.map(([label, entry]) => (
                  <li
                    key={`use-case-${label}`}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="font-medium">{label}</span>
                    <span className="text-right text-xs text-[#6a6581]">
                      {asString(entry.label) ?? "Unknown"} •{" "}
                      {formatPercent(asNumber(entry.score))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
