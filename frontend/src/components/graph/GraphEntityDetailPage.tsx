"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getGraphEntity,
  type GraphConnectedDocumentItem,
  type GraphConnectedEntityItem,
  type GraphEvidenceItem,
  type GraphRelationItem,
} from "@/lib/api/graph";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";

type GraphEntityDetailPageProps = {
  entityId: string;
};

type RelationDirection = "both" | "out" | "in";

const RELATIONSHIP_DIRECTIONS: RelationDirection[] = ["both", "out", "in"];

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

function groupString(value: string | null | undefined): string {
  return value && value.trim().length > 0 ? value : "—";
}

function relationOtherEntity(
  relation: GraphRelationItem,
  entityId: string,
  connectedEntities: Map<string, GraphConnectedEntityItem>,
): GraphConnectedEntityItem | null {
  const otherId =
    relation.from_entity_id === entityId
      ? relation.to_entity_id
      : relation.from_entity_id;
  return connectedEntities.get(otherId) ?? null;
}

function EvidenceCard({
  item,
  entityId,
}: {
  item: GraphEvidenceItem;
  entityId: string;
}) {
  const evidenceText = item.citation_text ?? item.evidence_text ?? "No excerpt";
  const documentHref = `/documents/${encodeURIComponent(item.source_document_id)}?chunk_id=${encodeURIComponent(item.chunk_id)}&back=${encodeURIComponent(`/graph/entities/${entityId}`)}`;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[#2a2640]">
            Document {item.source_document_id}
          </p>
          <p className="text-xs text-[#68647b]">
            Page {item.page_number ?? "—"} · Confidence{" "}
            {formatConfidence(item.confidence)}
          </p>
        </div>
        <Link
          href={documentHref}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-[#433e59] transition hover:bg-slate-50"
        >
          Open evidence
        </Link>
      </div>
      <p className="mt-3 rounded-xl bg-[#f8f7fc] p-3 text-sm text-[#4d4861]">
        {evidenceText}
      </p>
      <dl className="mt-3 grid gap-2 text-xs text-[#68647b] md:grid-cols-2">
        <div>
          <dt className="font-semibold text-[#433e59]">Citation</dt>
          <dd>{item.citation_reference ?? "—"}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[#433e59]">Connector</dt>
          <dd>{item.source_connector ?? "—"}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[#433e59]">Chunk</dt>
          <dd>{item.chunk_id}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[#433e59]">Source URL</dt>
          <dd>{item.external_url ?? "—"}</dd>
        </div>
      </dl>
    </article>
  );
}

export function GraphEntityDetailPage({
  entityId,
}: GraphEntityDetailPageProps) {
  const [relType, setRelType] = useState("");
  const [direction, setDirection] = useState<RelationDirection>("both");
  const [appliedRelType, setAppliedRelType] = useState("");
  const [appliedDirection, setAppliedDirection] =
    useState<RelationDirection>("both");

  const queryParams = useMemo(
    () => ({
      rel_type: appliedRelType.trim() || undefined,
      relationship_direction: appliedDirection,
      limit: 100,
    }),
    [appliedDirection, appliedRelType],
  );

  const query = useQuery({
    queryKey: queryKeys.graph.entity(entityId, queryParams),
    queryFn: () => getGraphEntity(entityId, queryParams),
  });

  const isInitialLoading = query.isLoading && !query.data;
  const isForbidden = isForbiddenError(query.error);
  const requestId = extractRequestIdFromError(query.error);
  const detail = query.data;

  const connectedEntities = useMemo(
    () =>
      new Map(
        (detail?.connected_entities ?? []).map((item) => [
          item.entity_id,
          item,
        ]),
      ),
    [detail?.connected_entities],
  );

  const relationRows = useMemo(() => {
    const entity = detail?.entity;
    if (!entity) {
      return [];
    }

    return (detail?.relationships ?? []).map((relation) => {
      const other = relationOtherEntity(
        relation,
        entity.entity_id,
        connectedEntities,
      );
      return {
        ...relation,
        other,
        isOutgoing: relation.from_entity_id === entity.entity_id,
      };
    });
  }, [connectedEntities, detail?.entity, detail?.relationships]);

  const onApplyFilters = () => {
    setAppliedRelType(relType);
    setAppliedDirection(direction);
  };

  if (isForbidden) {
    return (
      <ForbiddenState
        title="Graph entity restricted"
        description="You do not have permission to inspect graph data for this organization."
        requestId={requestId}
        backHref="/graph"
        backLabel="Back to graph explorer"
      />
    );
  }

  if (query.error) {
    return (
      <ErrorState
        title="Graph entity unavailable"
        description={getApiErrorMessage(query.error)}
        error={query.error}
        requestId={requestId}
        onRetry={() => void query.refetch()}
      />
    );
  }

  if (isInitialLoading) {
    return <LoadingState title="Loading entity details..." />;
  }

  if (!detail) {
    return (
      <EmptyState
        title="Entity not found"
        description="This entity may have been removed or you may not have access to it."
        action={
          <Link
            href="/graph"
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            Back to graph explorer
          </Link>
        }
      />
    );
  }

  const { entity } = detail;
  const summary = detail.summary;

  return (
    <section className="space-y-6">
      <header className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <Link
              href="/graph"
              className="text-sm font-semibold text-[#5d58a8] hover:underline"
            >
              ← Back to graph explorer
            </Link>
            <p className="mt-3 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Entity detail
            </p>
            <h1 className="mt-2 text-3xl font-extrabold text-[#2a2640]">
              {entity.canonical_name}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-[#ece8ff] px-3 py-1 text-xs font-bold tracking-[0.12em] text-[#3525cd] uppercase">
                {groupString(entity.entity_type)}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                Updated {formatDate(entity.last_updated_at)}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                Confidence {formatConfidence(entity.confidence)}
              </span>
            </div>
            <p className="mt-3 text-sm text-[#68647b]">
              Provenance-backed graph facts, connected documents, and related
              entities are summarized below.
            </p>
          </div>
          <div className="rounded-2xl bg-[#f5f3ff] px-4 py-3 text-sm text-[#4d4880]">
            <p className="font-semibold">Summary</p>
            <p>{summary.evidence_count} evidence links</p>
            <p>{summary.relationship_count} relationships</p>
          </div>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Aliases", value: summary.alias_count },
          { label: "Evidence", value: summary.evidence_count },
          { label: "Documents", value: summary.connected_document_count },
          { label: "Related entities", value: summary.connected_entity_count },
        ].map((card) => (
          <article
            key={card.label}
            className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm"
          >
            <p className="text-xs font-bold tracking-[0.12em] text-[#5d58a8] uppercase">
              {card.label}
            </p>
            <p className="mt-2 text-2xl font-extrabold text-[#2a2640]">
              {card.value}
            </p>
          </article>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <article className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-[#2a2640]">
                Relationships
              </h2>
              <p className="text-sm text-[#68647b]">
                Filter relationships and inspect the evidence trail.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
                Relationship type
                <input
                  value={relType}
                  onChange={(event) => setRelType(event.target.value)}
                  placeholder="OWNS"
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
                />
              </label>
              <label className="grid gap-1 text-sm font-semibold text-[#433e59]">
                Direction
                <select
                  value={direction}
                  onChange={(event) =>
                    setDirection(event.target.value as RelationDirection)
                  }
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-[#2a2640] transition outline-none focus:border-[#3525cd]"
                >
                  {RELATIONSHIP_DIRECTIONS.map((item) => (
                    <option key={item} value={item}>
                      {item === "both"
                        ? "Both directions"
                        : item === "out"
                          ? "Outgoing"
                          : "Incoming"}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={onApplyFilters}
                className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
              >
                Apply
              </button>
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-bold tracking-[0.12em] text-slate-500 uppercase">
                  <th className="px-4 py-3">Relation</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Confidence</th>
                  <th className="px-4 py-3">Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {relationRows.length > 0 ? (
                  relationRows.map((relation) => (
                    <tr
                      key={
                        relation.relation_id ??
                        `${relation.from_entity_id}-${relation.rel_type}-${relation.to_entity_id}`
                      }
                    >
                      <td className="px-4 py-4 text-sm text-[#2a2640]">
                        <div className="font-semibold">
                          {relation.isOutgoing
                            ? entity.canonical_name
                            : (relation.other?.canonical_name ??
                              relation.from_entity_id)}
                        </div>
                        <p className="text-xs text-[#68647b]">
                          {relation.rel_type} {relation.isOutgoing ? "→" : "←"}{" "}
                          {relation.isOutgoing
                            ? (relation.other?.canonical_name ??
                              relation.to_entity_id)
                            : entity.canonical_name}
                        </p>
                      </td>
                      <td className="px-4 py-4 text-sm text-[#4d4861]">
                        {relation.status ?? "—"}
                      </td>
                      <td className="px-4 py-4 text-sm text-[#4d4861]">
                        {formatConfidence(relation.confidence)}
                      </td>
                      <td className="px-4 py-4 text-sm text-[#4d4861]">
                        {groupString(
                          typeof relation.properties["evidence_text"] ===
                            "string"
                            ? relation.properties["evidence_text"]
                            : undefined,
                        )}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="px-4 py-8">
                      <EmptyState
                        compact
                        title="No relationships"
                        description="Adjust the relationship filters or inspect evidence sections below."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">
            Connected documents
          </h2>
          <div className="mt-4 space-y-3">
            {detail.connected_documents.length > 0 ? (
              detail.connected_documents.map((document) => (
                <div
                  key={document.document_id}
                  className="rounded-2xl border border-slate-200 bg-slate-50 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold text-[#2a2640]">
                        Document {document.document_id}
                      </p>
                      <p className="text-xs text-[#68647b]">
                        Pages {document.page_numbers.join(", ") || "—"} ·{" "}
                        {document.evidence_count} evidence links
                      </p>
                    </div>
                    <Link
                      href={`/documents/${encodeURIComponent(document.document_id)}?back=${encodeURIComponent(`/graph/entities/${entityId}`)}`}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-[#433e59] transition hover:bg-slate-50"
                    >
                      Open document
                    </Link>
                  </div>
                  <p className="mt-3 text-xs text-[#68647b]">
                    Connectors: {document.source_connectors.join(", ") || "—"}
                  </p>
                </div>
              ))
            ) : (
              <EmptyState
                compact
                title="No connected documents"
                description="This entity currently has no provenance-linked documents."
              />
            )}
          </div>
        </article>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <article className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">
            Connected entities
          </h2>
          <div className="mt-4 space-y-3">
            {detail.connected_entities.length > 0 ? (
              detail.connected_entities.map((related) => (
                <div
                  key={related.entity_id}
                  className="rounded-2xl border border-slate-200 bg-white p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <Link
                        href={`/graph/entities/${encodeURIComponent(related.entity_id)}`}
                        className="font-semibold text-[#2a2640] hover:underline"
                      >
                        {related.canonical_name ?? related.entity_id}
                      </Link>
                      <p className="text-xs text-[#68647b]">
                        {related.entity_type ?? "Entity"} ·{" "}
                        {related.relation_count} relationships
                      </p>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState
                compact
                title="No connected entities"
                description="Relationships have not been extracted yet for this entity."
              />
            )}
          </div>
        </article>

        <article className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Aliases</h2>
          <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-bold tracking-[0.12em] text-slate-500 uppercase">
                  <th className="px-4 py-3">Alias</th>
                  <th className="px-4 py-3">Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {detail.aliases.length > 0 ? (
                  detail.aliases.map((alias) => (
                    <tr key={alias.alias_id}>
                      <td className="px-4 py-4 text-sm text-[#2a2640]">
                        <p className="font-semibold">{alias.alias_name}</p>
                        <p className="text-xs text-[#68647b]">
                          Document {alias.source_document_id ?? "—"} · Page{" "}
                          {alias.page_number ?? "—"}
                        </p>
                      </td>
                      <td className="px-4 py-4 text-sm text-[#4d4861]">
                        {alias.evidence_text ?? "—"}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={2} className="px-4 py-8">
                      <EmptyState
                        compact
                        title="No aliases"
                        description="Only canonical names are available for this entity."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="rounded-3xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              Source evidence
            </h2>
            <p className="text-sm text-[#68647b]">
              Open the document chunk that supports each graph fact.
            </p>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {detail.evidence.length > 0 ? (
            detail.evidence.map((item) => (
              <EvidenceCard
                key={`${item.chunk_id}-${item.source_document_id}`}
                item={item}
                entityId={entityId}
              />
            ))
          ) : (
            <EmptyState
              title="No source evidence"
              description="This entity does not yet have provenance links."
            />
          )}
        </div>
      </section>
    </section>
  );
}
