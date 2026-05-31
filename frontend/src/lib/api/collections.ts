import { apiRequest } from "@/lib/api/request";
import type { DocumentListItemResponse } from "@/lib/api/documents";

export type CollectionAccessPolicy = "org_wide" | "restricted";

export type CollectionListItemResponse = {
  collection_id: string;
  name: string;
  description: string | null;
  owner_id: string;
  owner_email: string | null;
  document_count: number;
  indexed_count: number;
  access_policy: CollectionAccessPolicy;
  created_at: string;
  updated_at: string;
};

export type CollectionDetailResponse = CollectionListItemResponse & {
  created_by_email: string | null;
};

export type CollectionListResponse = {
  items: CollectionListItemResponse[];
  total: number;
};

export type CreateCollectionRequest = {
  name: string;
  description?: string | null;
  access_policy?: CollectionAccessPolicy;
};

export type UpdateCollectionRequest = {
  name?: string;
  description?: string | null;
  access_policy?: CollectionAccessPolicy;
};

export type DeleteCollectionResponse = {
  collection_id: string;
  archived: boolean;
};

export type CollectionDocumentsResponse = {
  items: DocumentListItemResponse[];
  total: number;
};

export type AddDocumentToCollectionResponse = {
  collection_id: string;
  document_id: string;
};

export type DocumentCollectionsResponse = {
  items: CollectionListItemResponse[];
};

export type ListCollectionsOptions = {
  limit?: number;
  offset?: number;
  name_query?: string;
};

export async function listCollections(
  options: ListCollectionsOptions = {},
): Promise<CollectionListResponse> {
  return apiRequest<CollectionListResponse>("/collections", {
    query: {
      limit: options.limit,
      offset: options.offset,
      name_query: options.name_query || undefined,
    },
  });
}

export async function getCollection(
  collectionId: string,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
  );
}

export async function createCollection(
  payload: CreateCollectionRequest,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>("/collections", {
    method: "POST",
    json: payload,
  });
}

export async function updateCollection(
  collectionId: string,
  payload: UpdateCollectionRequest,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function deleteCollection(
  collectionId: string,
): Promise<DeleteCollectionResponse> {
  return apiRequest<DeleteCollectionResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
    { method: "DELETE" },
  );
}

export async function listCollectionDocuments(
  collectionId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<CollectionDocumentsResponse> {
  return apiRequest<CollectionDocumentsResponse>(
    `/collections/${encodeURIComponent(collectionId)}/documents`,
    {
      query: {
        limit: options.limit,
        offset: options.offset,
      },
    },
  );
}

export async function addDocumentToCollection(
  collectionId: string,
  documentId: string,
): Promise<AddDocumentToCollectionResponse> {
  return apiRequest<AddDocumentToCollectionResponse>(
    `/collections/${encodeURIComponent(collectionId)}/documents`,
    {
      method: "POST",
      json: { document_id: documentId },
    },
  );
}

export async function removeDocumentFromCollection(
  collectionId: string,
  documentId: string,
): Promise<void> {
  await apiRequest<unknown>(
    `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
}

export async function getDocumentCollections(
  documentId: string,
): Promise<DocumentCollectionsResponse> {
  return apiRequest<DocumentCollectionsResponse>(
    `/documents/${encodeURIComponent(documentId)}/collections`,
  );
}

export async function setDocumentCollections(
  documentId: string,
  collectionIds: string[],
): Promise<DocumentCollectionsResponse> {
  return apiRequest<DocumentCollectionsResponse>(
    `/documents/${encodeURIComponent(documentId)}/collections`,
    {
      method: "PUT",
      json: { collection_ids: collectionIds },
    },
  );
}
