import { apiRequest } from "@/lib/api/request";

export type GraphEntitySearchItem = {
  entity_id: string;
  entity_type?: string | null;
  canonical_name: string;
  normalized_name?: string | null;
  aliases: string[];
  alias_count: number;
  workspace_id?: string | null;
  external_source_id?: string | null;
  resolution_status?: string | null;
  resolution_confidence?: number | null;
  confidence?: number | null;
  last_updated_at?: string | null;
  evidence_count: number;
  related_document_count: number;
};

export type GraphEntitySearchResponse = {
  items: GraphEntitySearchItem[];
  total: number;
  skip: number;
  limit: number;
  query?: string | null;
  entity_type?: string | null;
  min_confidence?: number | null;
  source_document_id?: string | null;
  source_connector?: string | null;
  rel_type?: string | null;
  relationship_direction: "out" | "in" | "both";
};

export type GraphAliasItem = {
  alias_id: string;
  entity_id: string;
  alias_name: string;
  normalized_name?: string | null;
  source_document_id?: string | null;
  chunk_id?: string | null;
  workspace_id?: string | null;
  source_external_id?: string | null;
  source_connector?: string | null;
  language?: string | null;
  confidence?: number | null;
  evidence_text?: string | null;
  page_number?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type GraphEvidenceItem = {
  chunk_id: string;
  source_document_id: string;
  workspace_id?: string | null;
  document_version_id?: string | null;
  page_number?: number | null;
  source_connector?: string | null;
  external_url?: string | null;
  extraction_run_id?: string | null;
  confidence?: number | null;
  evidence_text?: string | null;
  citation_text?: string | null;
  citation_reference?: string | null;
  created_at?: string | null;
};

export type GraphRelationItem = {
  relation_id?: string | null;
  from_entity_id: string;
  rel_type: string;
  to_entity_id: string;
  status?: string | null;
  confidence?: number | null;
  properties: Record<string, unknown>;
};

export type GraphConnectedDocumentItem = {
  document_id: string;
  page_numbers: number[];
  evidence_count: number;
  max_confidence: number;
  source_connectors: string[];
};

export type GraphConnectedEntityItem = {
  entity_id: string;
  entity_type?: string | null;
  canonical_name?: string | null;
  normalized_name?: string | null;
  relation_count: number;
};

export type GraphEntityDetailResponse = {
  entity: GraphEntitySearchItem;
  aliases: GraphAliasItem[];
  evidence: GraphEvidenceItem[];
  relationships: GraphRelationItem[];
  connected_documents: GraphConnectedDocumentItem[];
  connected_entities: GraphConnectedEntityItem[];
  summary: Record<string, number>;
};

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

export type DocumentGraphInsightEntityItem = {
  entity_id: string;
  entity_type?: string | null;
  canonical_name: string;
  confidence?: number | null;
  evidence_count: number;
};

export type DocumentGraphInsightEvidenceItem = {
  chunk_id: string;
  source_document_id: string;
  page_number?: number | null;
  confidence?: number | null;
  evidence_text?: string | null;
  citation_text?: string | null;
  citation_reference?: string | null;
  extraction_run_id?: string | null;
};

export type DocumentGraphInsightRunItem = {
  run_id: string;
  status: string;
  strategy?: string | null;
  entity_count?: number | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type DocumentGraphInsightsResponse = {
  entity_count: number;
  relation_count: number;
  avg_confidence?: number | null;
  entities_by_type: Record<string, number>;
  top_entities: DocumentGraphInsightEntityItem[];
  recent_evidence: DocumentGraphInsightEvidenceItem[];
  extraction_runs: DocumentGraphInsightRunItem[];
  last_run_at?: string | null;
};

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

export type GraphEntityTypeCountItem = {
  entity_type: string;
  count: number;
  avg_confidence?: number | null;
};

export type GraphStatsResponse = {
  total_entities: number;
  total_relations: number;
  avg_confidence?: number | null;
  low_confidence_count: number;
  entities_by_type: GraphEntityTypeCountItem[];
  graph_available: boolean;
};

export type GraphRelationshipListResponse = {
  items: GraphRelationItem[];
  total: number;
  skip: number;
  limit: number;
  has_more: boolean;
};

export type GraphNeighborItem = {
  entity_id: string;
  entity_type?: string | null;
  canonical_name?: string | null;
  normalized_name?: string | null;
  relation_count: number;
  confidence?: number | null;
  rel_type?: string | null;
  direction?: string | null;
};

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
