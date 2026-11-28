import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/api/query";

// The C2 factories replace ad-hoc literals; they must return the same arrays so
// cached data and invalidateQueries prefixes keep matching.
describe("queryKeys (C2 documents and collections factories)", () => {
  it("matches the former documents page literals", () => {
    expect(queryKeys.documentViews.indexingStatusSummary).toEqual([
      ...queryKeys.documents.all,
      "indexing-status-summary",
    ]);
    expect(queryKeys.documentViews.collectionPicker("q", 10)).toEqual([
      ...queryKeys.documents.all,
      "collection-picker",
      "q",
      10,
    ]);
  });

  it("matches the former collection picker literals", () => {
    expect(queryKeys.collectionViews.forUpload).toEqual([
      ...queryKeys.collections.all,
      "for-upload",
    ]);
    expect(queryKeys.collectionViews.forAssign).toEqual([
      ...queryKeys.collections.all,
      "for-assign",
    ]);
    expect(queryKeys.collectionViews.documentMembership("doc-1")).toEqual([
      ...queryKeys.collections.all,
      "doc",
      "doc-1",
    ]);
    expect(queryKeys.collectionViews.allDocuments("col-1")).toEqual([
      ...queryKeys.collections.documents("col-1", { limit: 200, offset: 0 }),
      "all",
    ]);
    expect(queryKeys.teamMemberPolicyPicker).toEqual([
      "team",
      "members",
      "policy-picker",
    ]);
    expect(queryKeys.citationChunk("doc-1", "chunk-1")).toEqual([
      "citation-chunk",
      "doc-1",
      "chunk-1",
    ]);
  });

  it("keeps the documents and collections invalidation prefixes", () => {
    const startsWith = (key: readonly unknown[], prefix: readonly unknown[]) =>
      prefix.every((part, index) => key[index] === part);
    expect(
      startsWith(
        queryKeys.documentViews.indexingStatusSummary,
        queryKeys.documents.all,
      ),
    ).toBe(true);
    expect(
      startsWith(
        queryKeys.collectionViews.allDocuments("col-1"),
        queryKeys.collections.all,
      ),
    ).toBe(true);
    expect(
      startsWith(
        queryKeys.collectionViews.documentMembership("doc-1"),
        queryKeys.collections.all,
      ),
    ).toBe(true);
  });
});
