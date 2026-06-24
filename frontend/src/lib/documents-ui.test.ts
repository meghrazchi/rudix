import { describe, expect, it } from "vitest";

import {
  canDeleteDocument,
  canForceReindexDocument,
  canReindexDocument,
  getDocumentLifecycleActionErrorMessage,
  resolveDocumentCapabilities,
  shouldPollDocumentList,
  shouldPollDocumentStatus,
} from "@/lib/documents-ui";
import type { DocumentListItemResponse } from "@/lib/api/documents";
import { normalizeApiError } from "@/lib/api/errors";

function documentWithStatus(
  status: DocumentListItemResponse["status"],
): DocumentListItemResponse {
  return {
    document_id: `doc-${status}`,
    filename: `sample-${status}.pdf`,
    file_type: "pdf",
    status,
    page_count: 2,
    chunk_count: 8,
    error_message: null,
    error_details: null,
    created_at: "2026-05-14T00:00:00Z",
    updated_at: "2026-05-14T00:00:00Z",
  };
}

describe("documents UI permissions", () => {
  it("grants owner/admin full document mutation capabilities", () => {
    expect(resolveDocumentCapabilities("owner")).toEqual({
      canUpload: true,
      canDelete: true,
      canReindex: true,
      canViewChunkFullText: true,
      canOverrideLanguage: true,
      canEditQuality: true,
    });
    expect(resolveDocumentCapabilities("admin")).toEqual({
      canUpload: true,
      canDelete: true,
      canReindex: true,
      canViewChunkFullText: true,
      canOverrideLanguage: true,
      canEditQuality: true,
    });
  });

  it("limits member and viewer capabilities", () => {
    expect(resolveDocumentCapabilities("member")).toEqual({
      canUpload: true,
      canDelete: true,
      canReindex: false,
      canViewChunkFullText: true,
      canOverrideLanguage: false,
      canEditQuality: false,
    });
    expect(resolveDocumentCapabilities("viewer")).toEqual({
      canUpload: false,
      canDelete: false,
      canReindex: false,
      canViewChunkFullText: false,
      canOverrideLanguage: false,
      canEditQuality: false,
    });
  });
});

describe("documents UI polling and action helpers", () => {
  it("polls only while statuses are transitional", () => {
    expect(shouldPollDocumentStatus("uploaded")).toBe(true);
    expect(shouldPollDocumentStatus("processing")).toBe(true);
    expect(shouldPollDocumentStatus("deleting")).toBe(true);
    expect(shouldPollDocumentStatus("indexed")).toBe(false);
    expect(shouldPollDocumentStatus("indexed", "extracting")).toBe(true);
    expect(shouldPollDocumentStatus("failed")).toBe(false);
    expect(shouldPollDocumentStatus("deleted")).toBe(false);
  });

  it("polls list when at least one transitional item exists", () => {
    expect(shouldPollDocumentList(undefined)).toBe(false);
    expect(shouldPollDocumentList([])).toBe(false);
    expect(
      shouldPollDocumentList([
        documentWithStatus("indexed"),
        documentWithStatus("failed"),
      ]),
    ).toBe(false);
    expect(
      shouldPollDocumentList([
        documentWithStatus("indexed"),
        documentWithStatus("processing"),
      ]),
    ).toBe(true);
  });

  it("allows safe actions based on backend-compatible statuses", () => {
    expect(canDeleteDocument("uploaded")).toBe(true);
    expect(canDeleteDocument("indexed")).toBe(true);
    expect(canDeleteDocument("deleting")).toBe(false);
    expect(canDeleteDocument("deleted")).toBe(false);

    expect(canReindexDocument("uploaded")).toBe(true);
    expect(canReindexDocument("indexed")).toBe(true);
    expect(canReindexDocument("failed")).toBe(true);
    expect(canReindexDocument("processing")).toBe(false);
    expect(canForceReindexDocument("processing")).toBe(true);
    expect(canForceReindexDocument("indexed")).toBe(false);
    expect(canReindexDocument("deleting")).toBe(false);
    expect(canReindexDocument("deleted")).toBe(false);
  });

  it("maps lifecycle conflict errors to user-friendly messages", () => {
    const conflictError = normalizeApiError({
      status: 409,
      payload: { detail: "conflict" },
    });

    expect(
      getDocumentLifecycleActionErrorMessage("delete", conflictError),
    ).toMatch(/cannot be deleted in its current lifecycle state/i);
    expect(
      getDocumentLifecycleActionErrorMessage("reindex", conflictError),
    ).toMatch(/cannot be re-indexed in its current lifecycle state/i);
  });
});
