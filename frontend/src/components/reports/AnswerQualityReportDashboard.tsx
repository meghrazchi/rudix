"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  DetailDrawer,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { useReportBackendData } from "@/components/reports/ReportBackendData";
import { getAnswerQualityDetail } from "@/lib/api/answer-quality";

function percent(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-xl border border-[#dfdced] bg-white p-4 shadow-sm">
      <p className="text-xs font-bold tracking-wide text-[#777287] uppercase">
        {label}
      </p>
      <p className="mt-2 text-3xl font-extrabold text-[#2a2640]">{value}</p>
    </article>
  );
}

export function AnswerQualityReportDashboard() {
  const t = useTranslations("reports.sections.answer-quality");
  const { answerQuality } = useReportBackendData();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [warning, setWarning] = useState("all");
  const detail = useQuery({
    queryKey: ["answer-quality-detail", selectedId],
    queryFn: () => getAnswerQualityDetail(selectedId as string),
    enabled: selectedId !== null,
  });
  const rows = useMemo(
    () =>
      (answerQuality?.items ?? []).filter(
        (row) => warning === "all" || row.warnings.includes(warning),
      ),
    [answerQuality?.items, warning],
  );
  const metrics = answerQuality?.metrics;

  return (
    <main className="grid gap-6">
      <ReportHeader title={t("label")} description={t("description")} />
      <section
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
        aria-label="Answer quality metrics"
      >
        <Metric
          label="Questions"
          value={String(metrics?.total_questions ?? 0)}
        />
        <Metric
          label="Average confidence"
          value={percent(metrics?.average_confidence ?? null)}
        />
        <Metric
          label="Citation support"
          value={percent(metrics?.average_citation_support ?? null)}
        />
        <Metric
          label="Not found"
          value={String(metrics?.not_found_count ?? 0)}
        />
        <Metric
          label="Missing citations"
          value={String(metrics?.missing_citations_count ?? 0)}
        />
        <Metric
          label="Stale-source warnings"
          value={String(metrics?.stale_source_warning_count ?? 0)}
        />
        <Metric
          label="Source conflicts"
          value={String(metrics?.source_conflict_count ?? 0)}
        />
        <Metric
          label="Unsupported claims removed"
          value={String(metrics?.unsupported_claims_removed ?? 0)}
        />
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-xl border border-[#dfdced] bg-white p-5 shadow-sm">
          <h2 className="font-bold text-[#2a2640]">
            Citation and confidence quality over time
          </h2>
          <div
            className="mt-4 h-72"
            role="img"
            aria-label="Answer confidence and citation support trend"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={answerQuality?.trends ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ebe8f4" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="average_confidence"
                  name="Confidence"
                  stroke="#6254d9"
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="average_citation_support"
                  name="Citation support"
                  stroke="#059669"
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="rounded-xl border border-[#dfdced] bg-white p-5 shadow-sm">
          <h2 className="font-bold text-[#2a2640]">
            Low-confidence answers by collection
          </h2>
          <ul className="mt-4 grid gap-3">
            {(answerQuality?.low_confidence_by_collection ?? []).map((item) => (
              <li
                key={item.collection_id ?? item.collection_name}
                className="flex justify-between rounded-lg bg-[#f7f5ff] px-3 py-2 text-sm"
              >
                <span>{item.collection_name}</span>
                <strong>{item.low_confidence_count}</strong>
              </li>
            ))}
          </ul>
          <h2 className="mt-6 font-bold text-[#2a2640]">
            Bad-answer feedback categories
          </h2>
          <ul className="mt-4 grid gap-3">
            {(answerQuality?.bad_feedback_categories ?? []).map((item) => (
              <li
                key={item.category}
                className="flex justify-between rounded-lg bg-rose-50 px-3 py-2 text-sm"
              >
                <span>{item.category.replaceAll("_", " ")}</span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              Answers needing review
            </h2>
            <p className="text-sm text-[#777287]">
              Open a row to inspect the answer and permission-safe sources.
            </p>
          </div>
          <label className="grid gap-1 text-xs font-semibold text-[#5f5b72]">
            Warning
            <select
              value={warning}
              onChange={(event) => setWarning(event.target.value)}
              className="rounded-lg border border-[#d7d4e7] bg-white px-3 py-2 text-sm"
            >
              <option value="all">All warnings</option>
              <option value="missing_citations">Missing citations</option>
              <option value="stale_source">Stale source</option>
              <option value="source_conflict">Source conflict</option>
              <option value="unsupported_claims_removed">
                Unsupported claims removed
              </option>
            </select>
          </label>
        </div>
        <div className="overflow-x-auto rounded-xl border border-[#dfdced] bg-white shadow-sm">
          <table className="w-full min-w-[1100px] text-sm">
            <thead className="bg-[#f7f5ff] text-xs text-[#5f5b72] uppercase">
              <tr>
                {[
                  "Question",
                  "User",
                  "Collection / source",
                  "Confidence",
                  "Citation support",
                  "Warnings",
                  "Feedback",
                  "Date",
                  "Action",
                ].map((heading) => (
                  <th className="px-3 py-3 text-start" key={heading}>
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#ebe8f4]">
              {rows.map((row) => (
                <tr key={row.message_id}>
                  <td className="max-w-xs px-3 py-3 font-medium text-[#2a2640]">
                    {row.question}
                  </td>
                  <td className="px-3 py-3">{row.user_name}</td>
                  <td className="px-3 py-3">
                    {row.collection_name ?? "—"}
                    <span className="block text-xs text-[#777287]">
                      {row.source_name ?? "No cited source"}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge
                      label={`${row.confidence_level} · ${percent(row.confidence)}`}
                      tone={
                        row.confidence_level === "high"
                          ? "healthy"
                          : row.confidence_level === "medium"
                            ? "warning"
                            : "critical"
                      }
                    />
                  </td>
                  <td className="px-3 py-3">
                    {percent(row.citation_support_score)}
                  </td>
                  <td className="px-3 py-3">
                    {row.warnings.length
                      ? row.warnings
                          .map((item) => item.replaceAll("_", " "))
                          .join(", ")
                      : "None"}
                  </td>
                  <td className="px-3 py-3">{row.feedback_status ?? "None"}</td>
                  <td className="px-3 py-3">
                    {new Date(row.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-3 py-3">
                    <button
                      type="button"
                      onClick={() => setSelectedId(row.message_id)}
                      className="font-bold text-[#3525cd]"
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-[#777287]">
          Showing {rows.length} of {answerQuality?.pagination.total ?? 0}{" "}
          permission-accessible answers.
        </p>
      </section>

      <DetailDrawer
        title="Answer quality details"
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
      >
        {detail.isLoading ? (
          <p>Loading answer details…</p>
        ) : detail.isError || !detail.data ? (
          <p role="alert">
            This answer is unavailable or you no longer have access to its
            sources.
          </p>
        ) : (
          <div className="grid gap-5 text-sm">
            <section>
              <h3 className="font-bold">Question</h3>
              <p className="mt-1 whitespace-pre-wrap">{detail.data.question}</p>
            </section>
            <section>
              <h3 className="font-bold">Final answer</h3>
              <p className="mt-1 whitespace-pre-wrap">
                {detail.data.final_answer}
              </p>
            </section>
            <section>
              <h3 className="font-bold">Confidence reason</h3>
              <p className="mt-1">
                {detail.data.confidence_reasons.join(", ") ||
                  "No reason recorded"}
              </p>
            </section>
            <section>
              <h3 className="font-bold">Warnings</h3>
              <p className="mt-1">
                {detail.data.warnings
                  .map((item) => item.replaceAll("_", " "))
                  .join(", ") || "None"}
              </p>
            </section>
            <section>
              <h3 className="font-bold">Sources used</h3>
              <ul className="mt-2 grid gap-2">
                {detail.data.sources.map((source) => (
                  <li
                    key={`${source.document_id}-${source.page_number ?? 0}`}
                    className="rounded bg-[#f7f5ff] p-2"
                  >
                    {source.document_name}
                    {source.page_number ? ` · page ${source.page_number}` : ""}
                    {source.collection_name
                      ? ` · ${source.collection_name}`
                      : ""}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h3 className="font-bold">Feedback</h3>
              <p className="mt-1">
                {detail.data.feedback_category?.replaceAll("_", " ") ??
                  "No feedback"}
                {detail.data.feedback_comment
                  ? ` · ${detail.data.feedback_comment}`
                  : ""}
              </p>
            </section>
            <div className="flex flex-wrap gap-2">
              {detail.data.review_item_id ? (
                <Link
                  href={`/admin/feedback-review?item=${detail.data.review_item_id}`}
                  className="rounded-lg bg-[#4434c7] px-3 py-2 font-bold text-white"
                >
                  Open review task
                </Link>
              ) : null}
              {detail.data.related_evaluation_case_id ? (
                <Link
                  href={`/evaluations?case=${detail.data.related_evaluation_case_id}`}
                  className="rounded-lg border border-[#6254d9] px-3 py-2 font-bold text-[#4434c7]"
                >
                  Open evaluation case
                </Link>
              ) : detail.data.review_item_id ? (
                <Link
                  href={`/admin/feedback-review?item=${detail.data.review_item_id}&action=convert`}
                  className="rounded-lg border border-[#6254d9] px-3 py-2 font-bold text-[#4434c7]"
                >
                  Convert to evaluation case
                </Link>
              ) : null}
            </div>
          </div>
        )}
      </DetailDrawer>
    </main>
  );
}
