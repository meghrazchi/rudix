import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type GraphEntitySearchItem = Served<Schemas["GraphEntitySearchItem"]>;

export type GraphEntitySearchResponse = Served<
  Schemas["GraphEntitySearchResponse"]
>;

export type GraphAliasItem = Served<Schemas["GraphAliasItem"]>;

export type GraphEvidenceItem = Served<Schemas["GraphEvidenceItem"]>;

export type GraphRelationItem = Served<Schemas["GraphRelationItem"]>;

export type GraphConnectedDocumentItem = Served<
  Schemas["GraphConnectedDocumentItem"]
>;

export type GraphConnectedEntityItem = Served<
  Schemas["GraphConnectedEntityItem"]
>;

export type GraphEntityDetailResponse = Served<
  Schemas["GraphEntityDetailResponse"]
>;

export type GraphEntitySearchParams = {
  query?: string | null;
  entity_type?: string | null;
  min_confidence?: number | null;
  source_document_id?: string | null;
  source_connector?: string | null;
  rel_type?: string | null;
  relationship_direction?: "out" | "in" | "both";
  skip?: number;
  limit?: number;
};

export async function listGraphEntities(
  params: GraphEntitySearchParams = {},
): Promise<GraphEntitySearchResponse> {
  return apiRequest<GraphEntitySearchResponse>("/graph/entities", {
    query: {
      query: params.query ?? undefined,
      entity_type: params.entity_type ?? undefined,
      min_confidence: params.min_confidence ?? undefined,
      source_document_id: params.source_document_id ?? undefined,
      source_connector: params.source_connector ?? undefined,
      rel_type: params.rel_type ?? undefined,
      relationship_direction: params.relationship_direction ?? undefined,
      skip: params.skip ?? undefined,
      limit: params.limit ?? undefined,
    },
  });
}

export async function getGraphEntity(
  entityId: string,
  params: Pick<
    GraphEntitySearchParams,
    "rel_type" | "relationship_direction" | "limit"
  > = {},
): Promise<GraphEntityDetailResponse> {
  return apiRequest<GraphEntityDetailResponse>(
    `/graph/entities/${encodeURIComponent(entityId)}`,
    {
      query: {
        rel_type: params.rel_type ?? undefined,
        relationship_direction: params.relationship_direction ?? undefined,
        limit: params.limit ?? undefined,
      },
    },
  );
}

export type DocumentGraphInsightEntityItem = Served<
  Schemas["DocumentGraphInsightEntityItem"]
>;

export type DocumentGraphInsightEvidenceItem = Served<
  Schemas["DocumentGraphInsightEvidenceItem"]
>;

export type DocumentGraphInsightRunItem = Served<
  Schemas["DocumentGraphInsightRunItem"]
>;

export type DocumentGraphInsightsResponse = Served<
  Schemas["DocumentGraphInsightsResponse"]
>;

export async function getDocumentGraphInsights(
  documentId: string,
): Promise<DocumentGraphInsightsResponse> {
  return apiRequest<DocumentGraphInsightsResponse>(
    `/graph/documents/${encodeURIComponent(documentId)}/insights`,
  );
}

// ------------------------------------------------------------------
// F269 — Knowledge Graph Explorer additions
// ------------------------------------------------------------------

export type GraphEntityTypeCountItem = Served<
  Schemas["GraphEntityTypeCountItem"]
>;

export type GraphStatsResponse = Served<Schemas["GraphStatsResponse"]>;

export type GraphRelationshipListResponse = Served<
  Schemas["GraphRelationshipListResponse"]
>;

export type GraphNeighborItem = Served<Schemas["GraphNeighborItem"]>;

export async function getGraphStats(): Promise<GraphStatsResponse> {
  return apiRequest<GraphStatsResponse>("/graph/stats");
}

export type ListGraphRelationshipsParams = {
  rel_type?: string | null;
  min_confidence?: number | null;
  skip?: number;
  limit?: number;
};

export async function listGraphRelationships(
  params: ListGraphRelationshipsParams = {},
): Promise<GraphRelationshipListResponse> {
  return apiRequest<GraphRelationshipListResponse>("/graph/relationships", {
    query: {
      rel_type: params.rel_type ?? undefined,
      min_confidence: params.min_confidence ?? undefined,
      skip: params.skip ?? undefined,
      limit: params.limit ?? undefined,
    },
  });
}

export type GetEntityNeighborsParams = {
  depth?: number;
  limit?: number;
  rel_type?: string | null;
};

export async function getEntityNeighbors(
  entityId: string,
  params: GetEntityNeighborsParams = {},
): Promise<GraphNeighborItem[]> {
  return apiRequest<GraphNeighborItem[]>(
    `/graph/entities/${encodeURIComponent(entityId)}/neighbors`,
    {
      query: {
        depth: params.depth ?? undefined,
        limit: params.limit ?? undefined,
        rel_type: params.rel_type ?? undefined,
      },
    },
  );
}
