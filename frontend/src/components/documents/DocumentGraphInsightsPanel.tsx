"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getDocumentGraphInsights,
  type DocumentGraphInsightEntityItem,
  type DocumentGraphInsightEvidenceItem,
  type DocumentGraphInsightRunItem,
} from "@/lib/api/graph";
import { queryKeys } from "@/lib/api/query";

type GraphExtractionStatus =
  | "pending"
  | "extracting"
  | "completed"
  | "failed"
  | "skipped"
  | null
  | undefined;

type DocumentGraphInsightsPanelProps = {
  documentId: string;
  graphExtractionStatus: GraphExtractionStatus;
  canReindex: boolean;
  isReindexPending: boolean;
  onReindexGraph: () => void;
};

function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function extractionRunStatusBadge(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "running") {
    return "rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-rose-800";
  }
  return "rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-600";
}

function isGraphUnavailableError(error: unknown): boolean {
  return isApiClientError(error) && error.status === 503;
}

function EntityTypeGroup({
  entityType,
  count,
  entities,
  documentId,
}: {
  entityType: string;
  count: number;
  entities: DocumentGraphInsightEntityItem[];
  documentId: string;
}) {
  const typeEntities = entities.filter(
    (e) => (e.entity_type ?? "Unknown") === entityType,
  );

  return (
    <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-xs font-bold text-[#3525cd]">
          {entityType}
        </span>
        <span className="text-xs text-[#69637f]">{count}</span>
      </div>
      <ul className="space-y-1">
        {typeEntities.slice(0, 8).map((entity) => (
          <li
            key={entity.entity_id}
            className="flex items-center justify-between gap-2"
          >
            <Link
              href={`/graph/entities/${encodeURIComponent(entity.entity_id)}?back=${encodeURIComponent(`/documents/${documentId}`)}`}
              className="truncate text-xs font-semibold text-[#3525cd] hover:underline"
            >
              {entity.canonical_name}
            </Link>
            <span className="shrink-0 text-[10px] text-[#69637f]">
              {formatConfidence(entity.confidence)}
            </span>
          </li>
        ))}
        {typeEntities.length > 8 ? (
          <li className="text-[10px] text-[#69637f]">
            +{typeEntities.length - 8} more
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function EvidenceCard({
  item,
  documentId,
}: {
  item: DocumentGraphInsightEvidenceItem;
  documentId: string;
}) {
  const snippet = item.citation_text ?? item.evidence_text ?? null;
  const chunkHref = `/documents/${encodeURIComponent(documentId)}?chunk_id=${encodeURIComponent(item.chunk_id)}`;

  return (
    <div className="rounded-lg border border-[#e9e6f5] bg-white p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] text-[#69637f]">
        {item.page_number != null ? <span>Page {item.page_number}</span> : null}
        {item.confidence != null ? (
          <span>Confidence {formatConfidence(item.confidence)}</span>
        ) : null}
        <Link
          href={chunkHref}
          className="ml-auto text-[10px] font-semibold text-[#3525cd] hover:underline"
        >
          View chunk
        </Link>
      </div>
      {snippet ? (
        <p className="rounded-r border-l-2 border-[#3525cd]/40 bg-[#faf9ff] py-1 pr-2 pl-2 text-xs text-[#4d4861] italic">
          {snippet.length > 280 ? `${snippet.slice(0, 280)}…` : snippet}
        </p>
      ) : (
        <p className="text-[10px] text-[#69637f]">No excerpt available</p>
      )}
      {item.citation_reference ? (
        <p className="mt-1 text-[10px] text-[#69637f]">
          {item.citation_reference}
        </p>
      ) : null}
    </div>
  );
}

function ExtractionRunRow({ run }: { run: DocumentGraphInsightRunItem }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#e9e6f5] bg-white px-3 py-2 text-xs">
      <span className={extractionRunStatusBadge(run.status)}>{run.status}</span>
      <span className="text-[#69637f]">
        {formatDate(run.updated_at ?? run.created_at)}
      </span>
      {run.entity_count != null ? (
        <span className="text-[#69637f]">{run.entity_count} entities</span>
      ) : null}
      {run.strategy ? (
        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
          {run.strategy}
        </span>
      ) : null}
      {run.error ? (
        <span
          className="ml-auto max-w-[180px] truncate text-rose-600"
          title={run.error}
        >
          {run.error}
        </span>
      ) : null}
    </div>
  );
}

export function DocumentGraphInsightsPanel({
  documentId,
  graphExtractionStatus,
  canReindex,
  isReindexPending,
  onReindexGraph,
}: DocumentGraphInsightsPanelProps) {
  const shouldFetch =
    graphExtractionStatus === "completed" || graphExtractionStatus === "failed";

  const insightsQuery = useQuery({
    queryKey: queryKeys.graph.documentInsights(documentId),
    queryFn: () => getDocumentGraphInsights(documentId),
    enabled: shouldFetch,
  });

  const graphUnavailable = isGraphUnavailableError(insightsQuery.error);

  if (!shouldFetch && !graphExtractionStatus) {
    return (
      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <SectionHeader />
        <p className="mt-2 text-sm text-[#69637f]">
          Graph extraction has not been configured for this document.
        </p>
      </div>
    );
  }

  if (graphExtractionStatus === "skipped") {
    return (
      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <SectionHeader />
        <p className="mt-2 text-sm text-[#69637f]">
          Graph extraction was skipped for this document. Enterprise Graph may
          not be enabled for this organization.
        </p>
      </div>
    );
  }

  if (
    graphExtractionStatus === "pending" ||
    graphExtractionStatus === "extracting"
  ) {
    return (
      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <SectionHeader />
        <div className="mt-3 flex items-center gap-2 text-sm text-[#5d58a8]">
          <span
            className="material-symbols-outlined animate-spin text-[16px]"
            aria-hidden="true"
          >
            sync
          </span>
          {graphExtractionStatus === "extracting"
            ? "Graph extraction is in progress…"
            : "Graph extraction is queued…"}
        </div>
      </div>
    );
  }

  if (graphUnavailable) {
    return (
      <div
        data-testid="graph-insights-unavailable"
        className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4"
      >
        <SectionHeader />
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-sm font-semibold text-amber-700">
            Enterprise Graph unavailable
          </p>
          <p className="mt-0.5 text-xs text-amber-600">
            The graph database is currently offline or not configured. Document
            details continue to work normally.
          </p>
        </div>
      </div>
    );
  }

  if (insightsQuery.isLoading) {
    return (
      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <SectionHeader />
        <LoadingState compact title="Loading graph insights…" />
      </div>
    );
  }

  if (insightsQuery.isError && !graphUnavailable) {
    return (
      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <SectionHeader />
        <ErrorState
          compact
          error={insightsQuery.error}
          description={getApiErrorMessage(insightsQuery.error)}
          onRetry={() => void insightsQuery.refetch()}
        />
      </div>
    );
  }

  const data = insightsQuery.data;

  if (!data) {
    return null;
  }

  const entityTypes = Object.entries(data.entities_by_type).sort(
    ([, a], [, b]) => b - a,
  );
  const hasEntities = data.entity_count > 0;
  const hasEvidence = data.recent_evidence.length > 0;

  return (
    <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <SectionHeader />
          {graphExtractionStatus === "failed" ? (
            <p className="mt-1 text-xs font-semibold text-rose-600">
              Last extraction failed — see run history below.
            </p>
          ) : null}
        </div>
        {canReindex ? (
          <button
            type="button"
            aria-label="Re-run graph extraction"
            disabled={isReindexPending}
            onClick={onReindexGraph}
            className="inline-flex shrink-0 items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-2.5 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span
              aria-hidden="true"
              className="material-symbols-outlined text-[14px]"
            >
              schema
            </span>
            {isReindexPending ? "Queueing…" : "Re-run graph extraction"}
          </button>
        ) : null}
      </div>

      {/* Summary stats */}
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatCard label="Entities" value={data.entity_count} />
        <StatCard label="Relations" value={data.relation_count} />
        <StatCard
          label="Avg confidence"
          value={
            data.avg_confidence != null
              ? `${Math.round(data.avg_confidence * 100)}%`
              : "—"
          }
        />
        <StatCard
          label="Last run"
          value={data.last_run_at ? formatDate(data.last_run_at) : "—"}
          small
        />
      </div>

      {!hasEntities ? (
        <EmptyState
          compact
          title="No entities extracted"
          description={
            graphExtractionStatus === "failed"
              ? "Graph extraction failed. Re-run to retry."
              : "No entities were found in this document."
          }
        />
      ) : (
        <>
          {/* Entities by type */}
          <div className="mb-4">
            <h5 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Entities by type
            </h5>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {entityTypes.map(([type, count]) => (
                <EntityTypeGroup
                  key={type}
                  entityType={type}
                  count={count}
                  entities={data.top_entities}
                  documentId={documentId}
                />
              ))}
            </div>
          </div>

          {/* Evidence snippets */}
          {hasEvidence ? (
            <div className="mb-4">
              <h5 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Evidence snippets
              </h5>
              <div className="grid gap-2 sm:grid-cols-2">
                {data.recent_evidence.map((item) => (
                  <EvidenceCard
                    key={`${item.chunk_id}-${item.source_document_id}`}
                    item={item}
                    documentId={documentId}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}

      {/* Extraction run history */}
      {data.extraction_runs.length > 0 ? (
        <div>
          <h5 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Extraction run history
          </h5>
          <div className="space-y-1">
            {data.extraction_runs.map((run) => (
              <ExtractionRunRow key={run.run_id} run={run} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SectionHeader() {
  return (
    <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
      Graph insights
    </h4>
  );
}

function StatCard({
  label,
  value,
  small = false,
}: {
  label: string;
  value: string | number;
  small?: boolean;
}) {
  return (
    <div className="rounded-md border border-[#e4e1f2] bg-white px-3 py-2">
      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p
        className={`mt-1 font-extrabold text-[#2a2640] ${small ? "text-xs" : "text-lg"}`}
      >
        {value}
      </p>
    </div>
  );
}
