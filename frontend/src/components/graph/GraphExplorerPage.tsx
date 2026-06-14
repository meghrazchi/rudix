"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { listGraphEntities, type GraphEntitySearchItem } from "@/lib/api/graph";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";

const PAGE_SIZE = 20;

type DraftFilters = {
  query: string;
  entityType: string;
  minConfidence: string;
  sourceDocumentId: string;
  sourceConnector: string;
  relType: string;
  relationshipDirection: "both" | "out" | "in";
};

const ENTITY_TYPES = [
  "",
  "Entity",
  "Person",
  "Organization",
  "Customer",
  "Vendor",
  "Product",
  "Project",
  "Policy",
  "Contract",
  "Control",
  "Requirement",
  "Risk",
  "Ticket",
  "System",
  "Process",
  "Obligation",
];

const RELATIONSHIP_DIRECTIONS: DraftFilters["relationshipDirection"][] = [
  "both",
  "out",
  "in",
];

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

function initials(value: string): string {
  const parts = value
    .split(/[\s._-]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return "G";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function entityTypeLabel(value: string | null | undefined): string {
  return value && value.trim().length > 0 ? value : "Entity";
}

function entityBadgeClass(entityType: string | null | undefined): string {
  const normalized = (entityType ?? "").toLowerCase();
  if (normalized === "organization") {
    return "bg-sky-100 text-sky-800";
  }
  if (normalized === "person") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (normalized === "vendor" || normalized === "customer") {
    return "bg-amber-100 text-amber-800";
  }
  if (normalized === "policy" || normalized === "contract") {
    return "bg-violet-100 text-violet-800";
  }
  return "bg-slate-100 text-slate-700";
}

function createInitialFilters(): DraftFilters {
  return {
    query: "",
    entityType: "",
    minConfidence: "",
    sourceDocumentId: "",
    sourceConnector: "",
    relType: "",
    relationshipDirection: "both",
  };
}

function buildSearchParams(
  filters: DraftFilters,
  page: number,
): {
  query?: string;
  entity_type?: string;
  min_confidence?: number;
  source_document_id?: string;
  source_connector?: string;
  rel_type?: string;
  relationship_direction: "both" | "out" | "in";
  skip: number;
  limit: number;
} {
  const parsedConfidence = Number.parseFloat(filters.minConfidence);
  return {
    query: filters.query.trim() || undefined,
    entity_type: filters.entityType.trim() || undefined,
    min_confidence:
      Number.isFinite(parsedConfidence) && parsedConfidence >= 0
        ? Math.min(parsedConfidence, 1)
        : undefined,
    source_document_id: filters.sourceDocumentId.trim() || undefined,
    source_connector: filters.sourceConnector.trim() || undefined,
    rel_type: filters.relType.trim() || undefined,
    relationship_direction: filters.relationshipDirection,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
}

function SearchResultRow({ item }: { item: GraphEntitySearchItem }) {
  const aliasPreview =
    item.aliases.length > 0 ? item.aliases.slice(0, 3).join(", ") : "—";

  return (
    <tr className="border-t border-slate-100">
      <td className="px-4 py-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#ece8ff] text-sm font-bold text-[#3525cd]">
            {initials(item.canonical_name)}
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/graph/entities/${encodeURIComponent(item.entity_id)}`}
                className="font-semibold text-[#1f1c2e] hover:underline"
              >
                {item.canonical_name}
              </Link>
              <span
                className={`rounded-full px-2 py-1 text-[11px] font-bold tracking-[0.12em] uppercase ${entityBadgeClass(
                  item.entity_type,
                )}`}
              >
                {entityTypeLabel(item.entity_type)}
              </span>
            </div>
            <p className="mt-1 text-xs text-[#68647b]">ID: {item.entity_id}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">
        {formatConfidence(item.confidence)}
      </td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">{aliasPreview}</td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">
        {item.evidence_count}
      </td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">
        {item.related_document_count}
      </td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">
        {formatDate(item.last_updated_at)}
      </td>
      <td className="px-4 py-4 text-sm text-[#4d4861]">
        {item.resolution_status ?? "—"}
      </td>
    </tr>
  );
}

export function GraphExplorerPage() {
  const [draftFilters, setDraftFilters] =
    useState<DraftFilters>(createInitialFilters);
  const [activeFilters, setActiveFilters] =
    useState<DraftFilters>(createInitialFilters);
  const [page, setPage] = useState(0);

  const searchParams = useMemo(
    () => buildSearchParams(activeFilters, page),
    [activeFilters, page],
  );
  const query = useQuery({
    queryKey: queryKeys.graph.entities(searchParams),
    queryFn: () => listGraphEntities(searchParams),
    placeholderData: (previous) => previous,
  });

  const isInitialLoading = query.isLoading && !query.data;
  const isForbidden = isForbiddenError(query.error);
  const requestId = extractRequestIdFromError(query.error);

  const total = query.data?.total ?? 0;
  const items = query.data?.items ?? [];
  const hasNextPage =
    items.length === PAGE_SIZE && (page + 1) * PAGE_SIZE < total;
  const hasPrevPage = page > 0;

  const onSubmit = () => {
    setActiveFilters(draftFilters);
    setPage(0);
  };

  const onReset = () => {
    const next = createInitialFilters();
    setDraftFilters(next);
    setActiveFilters(next);
    setPage(0);
  };

  if (isForbidden) {
    return (
      <ForbiddenState
        title="Graph explorer restricted"
        description="You do not have permission to view graph data for this organization."
        requestId={requestId}
        backHref="/dashboard"
        backLabel="Back to dashboard"
      />
    );
  }

  if (query.error) {
    return (
      <ErrorState
        title="Graph explorer unavailable"
        description={getApiErrorMessage(query.error)}
        error={query.error}
        requestId={requestId}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-3 rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Enterprise Graph
            </p>
            <h1 className="mt-2 text-3xl font-extrabold text-[#2a2640]">
              Graph explorer
            </h1>
            <p className="mt-2 text-sm text-[#68647b]">
              Search evidence-backed entities, inspect relationships, and open
              source evidence from the same interface.
            </p>
          </div>
          <div className="rounded-2xl bg-[#f5f3ff] px-4 py-3 text-sm text-[#4d4880]">
            <p className="font-semibold">Results</p>
            <p>{total.toLocaleString()} matching entities</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Search
            <input
              value={draftFilters.query}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  query: event.target.value,
                }))
              }
              placeholder="Entity name, alias, or external source"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Entity type
            <select
              value={draftFilters.entityType}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  entityType: event.target.value,
                }))
              }
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            >
              {ENTITY_TYPES.map((entityType) => (
                <option key={entityType || "all"} value={entityType}>
                  {entityType || "All entity types"}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Minimum confidence
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={draftFilters.minConfidence}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  minConfidence: event.target.value,
                }))
              }
              placeholder="0.75"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Source document
            <input
              value={draftFilters.sourceDocumentId}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  sourceDocumentId: event.target.value,
                }))
              }
              placeholder="Document ID"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Source connector
            <input
              value={draftFilters.sourceConnector}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  sourceConnector: event.target.value,
                }))
              }
              placeholder="confluence"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Relationship type
            <input
              value={draftFilters.relType}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  relType: event.target.value,
                }))
              }
              placeholder="OWNS"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
            Relationship direction
            <select
              value={draftFilters.relationshipDirection}
              onChange={(event) =>
                setDraftFilters((current) => ({
                  ...current,
                  relationshipDirection: event.target
                    .value as DraftFilters["relationshipDirection"],
                }))
              }
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
            >
              <option value="both">Both directions</option>
              <option value="out">Outgoing</option>
              <option value="in">Incoming</option>
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onSubmit}
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            Search
          </button>
          <button
            type="button"
            onClick={onReset}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-[#433e59] transition hover:bg-slate-50"
          >
            Reset
          </button>
        </div>
      </header>

      {isInitialLoading ? (
        <LoadingState title="Loading graph explorer..." />
      ) : null}

      {!isInitialLoading && items.length === 0 ? (
        <EmptyState
          title="No graph entities found"
          description="Try broadening the search query, lowering confidence, or clearing relationship filters."
          action={
            <button
              type="button"
              onClick={onReset}
              className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
            >
              Clear filters
            </button>
          }
        />
      ) : null}

      {!isInitialLoading && items.length > 0 ? (
        <section className="space-y-4 rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-[#2a2640]">
                Entity results
              </h2>
              <p className="text-sm text-[#68647b]">
                Showing {items.length} of {total.toLocaleString()} entities
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={!hasPrevPage}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-[#433e59] transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!hasNextPage}
                onClick={() => setPage((current) => current + 1)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-[#433e59] transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-bold tracking-[0.12em] text-slate-500 uppercase">
                  <th className="px-4 py-3">Entity</th>
                  <th className="px-4 py-3">Confidence</th>
                  <th className="px-4 py-3">Aliases</th>
                  <th className="px-4 py-3">Evidence</th>
                  <th className="px-4 py-3">Documents</th>
                  <th className="px-4 py-3">Updated</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {items.map((item) => (
                  <SearchResultRow key={item.entity_id} item={item} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 text-sm text-[#68647b]">
            <p>
              Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
            </p>
            <p>
              Use the filters to narrow the graph to evidence-backed records.
            </p>
          </div>
        </section>
      ) : null}
    </section>
  );
}
