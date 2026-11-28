import {
  listCollectionDocuments,
  type CollectionDocumentItem,
  type CollectionDocumentsResponse,
} from "@/lib/api/collections";

/** Largest page the collection documents endpoint serves (`limit` le=200). */
export const COLLECTION_DOCS_MAX_PAGE = 200;

/**
 * Every document of a collection, read page by page, for uses that need the
 * whole membership (add/remove diffs, chat scope) rather than a visible page.
 */
export async function fetchAllCollectionDocuments(
  collectionId: string,
): Promise<CollectionDocumentsResponse> {
  const items: CollectionDocumentItem[] = [];
  let total = 0;
  for (let offset = 0; ; offset += COLLECTION_DOCS_MAX_PAGE) {
    // The first request matches the former single-page call exactly.
    const page = await listCollectionDocuments(
      collectionId,
      offset > 0
        ? { limit: COLLECTION_DOCS_MAX_PAGE, offset }
        : { limit: COLLECTION_DOCS_MAX_PAGE },
    );
    const pageItems = page.items ?? [];
    items.push(...pageItems);
    total = page.total ?? items.length;
    if (pageItems.length === 0 || items.length >= total) {
      break;
    }
  }
  return { items, total };
}
