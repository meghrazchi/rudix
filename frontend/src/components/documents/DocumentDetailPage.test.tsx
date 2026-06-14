import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentDetailPage } from "@/components/documents/DocumentDetailPage";
import { normalizeApiError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getDocument: vi.fn(),
  getDocumentStatus: vi.fn(),
  getDocumentChunks: vi.fn(),
  deleteDocument: vi.fn(),
  reindexDocument: vi.fn(),
  reindexDocumentGraph: vi.fn(),
  downloadDocumentFile: vi.fn(),
  overrideDocumentLanguage: vi.fn(),
  configureDocumentOcr: vi.fn(),
}));

const mockChunkingApi = vi.hoisted(() => ({
  getChunkingStrategyCatalog: vi.fn(),
  listChunkingProfiles: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  getDocument: (documentId: string) => mockApi.getDocument(documentId),
  getDocumentStatus: (documentId: string) =>
    mockApi.getDocumentStatus(documentId),
  getDocumentChunks: (documentId: string, options?: unknown) =>
    mockApi.getDocumentChunks(documentId, options),
  deleteDocument: (documentId: string) => mockApi.deleteDocument(documentId),
  reindexDocument: (documentId: string, payload?: unknown) =>
    mockApi.reindexDocument(documentId, payload),
  reindexDocumentGraph: (documentId: string) =>
    mockApi.reindexDocumentGraph(documentId),
  downloadDocumentFile: (documentId: string) =>
    mockApi.downloadDocumentFile(documentId),
  overrideDocumentLanguage: (documentId: string, payload: unknown) =>
    mockApi.overrideDocumentLanguage(documentId, payload),
  configureDocumentOcr: (documentId: string, payload: unknown) =>
    mockApi.configureDocumentOcr(documentId, payload),
  UPLOAD_LANGUAGES: [
    { code: "en", label: "English" },
    { code: "de", label: "German" },
    { code: "es", label: "Spanish" },
    { code: "fr", label: "French" },
  ],
  OCR_LANGUAGES: [
    { code: "en", label: "English", tesseract: "eng" },
    { code: "de", label: "German", tesseract: "deu" },
    { code: "es", label: "Spanish", tesseract: "spa" },
    { code: "fr", label: "French", tesseract: "fra" },
  ],
}));

vi.mock("@/lib/api/chunking-profiles", () => ({
  getChunkingStrategyCatalog: () =>
    mockChunkingApi.getChunkingStrategyCatalog(),
  listChunkingProfiles: () => mockChunkingApi.listChunkingProfiles(),
}));

function renderPage(documentId = "doc-1") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentDetailPage documentId={documentId} />
    </QueryClientProvider>,
  );
}

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    mockNavigation.searchParams = new URLSearchParams();
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };
    mockApi.getDocument.mockReset();
    mockApi.getDocumentStatus.mockReset();
    mockApi.getDocumentChunks.mockReset();
    mockApi.deleteDocument.mockReset();
    mockApi.reindexDocument.mockReset();
    mockApi.reindexDocumentGraph.mockReset();
    mockApi.downloadDocumentFile.mockReset();
    mockApi.overrideDocumentLanguage.mockReset();
    mockApi.configureDocumentOcr.mockReset();
    Object.defineProperty(window, "confirm", {
      writable: true,
      value: vi.fn(() => true),
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });

    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 12,
      chunk_count: 120,
      checksum: "abc123",
      error_message: null,
      error_details: null,
      language: "en",
      chunking_diagnostics: {
        strategy: "adaptive_hybrid",
        selected_strategy: "page_aware",
        profile_version: "1.0",
        profile_source: "custom_profile",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        embedding_model: "text-embedding-3-small",
        index_version: "v1",
        ocr_applied: true,
        hierarchical_mode: false,
        parent_chunk_count: null,
        child_chunk_count: null,
        reason_codes: ["pdf_ocr_applied"],
        adaptive_signals: {
          file_type: "pdf",
          page_count: 12,
          total_token_count: 5200,
          ocr_applied: true,
          heading_density: 0.3,
          avg_chars_per_page: null,
          avg_paragraph_tokens: null,
        },
        token_distribution: {
          min_tokens: 120,
          max_tokens: 260,
          avg_tokens: 188.5,
          total_tokens: 7917,
        },
      },
      lifecycle_timeline: [
        {
          step: "extract",
          label: "Extract",
          description: "Extract raw text and metadata from source files.",
          status: "completed",
          document_id: "doc-1",
          pipeline_run_id: "run-1",
          pipeline_type: "document.process",
          started_at: "2026-05-15T09:59:00Z",
          completed_at: "2026-05-15T10:00:00Z",
          duration_ms: 1000,
          logs: ["extracted 12 pages"],
        },
      ],
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValue({
      document_id: "doc-1",
      status: "indexed",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentChunks.mockResolvedValue({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          section_path: "Policy > Overview",
          language: "en",
          chunk_level: 0,
          child_count: 0,
          source_start_offset: 0,
          source_end_offset: 240,
          text_preview: "Preview text for the first chunk.",
          text: null,
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: false,
    });
    mockApi.deleteDocument.mockResolvedValue({
      document_id: "doc-1",
      status: "deleting",
    });
    mockApi.reindexDocument.mockResolvedValue({
      document_id: "doc-1",
      status: "processing",
      queue_status: "queued",
    });
    mockApi.downloadDocumentFile.mockResolvedValue(
      new Blob(["fake file payload"], { type: "application/pdf" }),
    );
    mockChunkingApi.getChunkingStrategyCatalog.mockReset();
    mockChunkingApi.listChunkingProfiles.mockReset();
    mockChunkingApi.getChunkingStrategyCatalog.mockResolvedValue({
      strategies: [
        {
          name: "adaptive_hybrid",
          display_name: "Adaptive Hybrid",
          description: "Adaptive default.",
          suitable_for: ["mixed content"],
          requires_page_structure: false,
          supports_hierarchical: false,
        },
        {
          name: "page_aware",
          display_name: "Page Aware",
          description: "Preserve page boundaries.",
          suitable_for: ["pdf"],
          requires_page_structure: true,
          supports_hierarchical: false,
        },
      ],
      default_config: {
        strategy: "adaptive_hybrid",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        language: null,
        min_tokens: 88,
        strategy_options: {},
      },
      feature_chunking_profiles_enabled: true,
    });
    mockChunkingApi.listChunkingProfiles.mockResolvedValue({
      profiles: [
        {
          profile_id: "profile-1",
          organization_id: "org-1",
          name: "Operations Default",
          slug: "operations-default",
          config: {
            strategy: "adaptive_hybrid",
            chunk_size_tokens: 700,
            chunk_overlap_tokens: 120,
            language: "en",
            min_tokens: 88,
            strategy_options: {},
          },
          is_default: true,
          is_system: false,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:00:00Z",
          created_by_user_id: "u-1",
          updated_by_user_id: "u-1",
        },
      ],
      total: 1,
      has_org_default: true,
    });
  });

  it("renders indexed metadata and actions with preserved back link", async () => {
    mockNavigation.searchParams = new URLSearchParams({
      back: "/documents?status=failed&sort_by=updated_at&sort_order=asc&offset=20",
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "policy.pdf" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Document ID:/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/doc-1/).length).toBeGreaterThan(0);
    expect(screen.getByText("Lifecycle timeline")).toBeInTheDocument();
    expect(screen.getByText("Extracted")).toBeInTheDocument();
    expect(screen.getByText("extracted 12 pages")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to documents" }),
    ).toHaveAttribute(
      "href",
      "/documents?status=failed&sort_by=updated_at&sort_order=asc&offset=20",
    );
    expect(screen.getByRole("link", { name: "Ask in Chat" })).toHaveAttribute(
      "href",
      "/chat?document_id=doc-1",
    );
    expect(screen.getByRole("link", { name: "View Pipeline" })).toHaveAttribute(
      "href",
      "/rag-pipeline?run_type=document.process&document_id=doc-1",
    );
    await userEvent.click(screen.getByText("More actions"));
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeEnabled();
    expect(
      screen.getByRole("heading", { name: "Chunking diagnostics" }),
    ).toBeInTheDocument();
    expect(screen.getByText("pdf_ocr_applied")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));
    expect(await screen.findByText("Chunk #1")).toBeInTheDocument();
    expect(
      await screen.findByText("Model text-embedding-3-small"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Preview text for the first chunk."),
    ).toBeInTheDocument();
    expect(screen.getByText("Document preview")).toBeInTheDocument();
    expect(screen.getByText("View Original PDF")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /include full chunk text/i }),
    ).toBeInTheDocument();
  });

  it("downloads the original file from the preview card", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "policy.pdf" });
    await userEvent.click(
      screen.getByRole("button", { name: /download original file/i }),
    );

    await waitFor(() => {
      expect(mockApi.downloadDocumentFile).toHaveBeenCalledWith("doc-1");
    });
  });

  it("shows inline copied feedback that fades out for document metadata", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "policy.pdf" });
    await userEvent.click(
      screen.getByRole("button", { name: "Copy document id" }),
    );

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("doc-1");
    const copiedLabel = await screen.findByText("Copied");
    expect(copiedLabel).toBeInTheDocument();

    await waitFor(
      () => {
        expect(copiedLabel).toHaveClass("opacity-0");
      },
      { timeout: 2000 },
    );

    await waitFor(
      () => {
        expect(screen.queryByText("Copied")).not.toBeInTheDocument();
      },
      { timeout: 2500 },
    );
  });

  it("fetches full chunk text when full-text toggle is enabled", async () => {
    mockApi.getDocumentChunks.mockResolvedValueOnce({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          section_path: "Policy > Overview",
          language: "en",
          chunk_level: 0,
          child_count: 0,
          source_start_offset: 0,
          source_end_offset: 240,
          text_preview: "Preview text for the first chunk.",
          text: null,
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: false,
    });
    mockApi.getDocumentChunks.mockResolvedValueOnce({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          section_path: "Policy > Overview",
          language: "en",
          chunk_level: 0,
          child_count: 0,
          source_start_offset: 0,
          source_end_offset: 240,
          text_preview: "Preview text for the first chunk.",
          text: "FULL CHUNK TEXT",
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: true,
    });

    renderPage();

    await screen.findByRole("heading", { name: "policy.pdf" });
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));
    expect(
      await screen.findByText("Preview text for the first chunk."),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("checkbox", { name: /include full chunk text/i }),
    );

    await waitFor(() => {
      expect(mockApi.getDocumentChunks).toHaveBeenCalledWith(
        "doc-1",
        expect.objectContaining({ include_full_text: true }),
      );
    });
    expect(await screen.findByText("FULL CHUNK TEXT")).toBeInTheDocument();
  });

  it("filters chunk samples by metadata without exposing empty-state confusion", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "policy.pdf" });
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));

    expect(
      await screen.findByText("Section Policy > Overview"),
    ).toBeInTheDocument();
    await userEvent.type(
      screen.getByRole("textbox", { name: /search sample chunks/i }),
      "overview",
    );
    expect(
      await screen.findByText("Section Policy > Overview"),
    ).toBeInTheDocument();

    await userEvent.clear(
      screen.getByRole("textbox", { name: /search sample chunks/i }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: /search sample chunks/i }),
      "missing-section",
    );
    expect(
      await screen.findByText("No chunk samples matched this filter."),
    ).toBeInTheDocument();
  });

  it("shows failed document safe error details and disables ask in chat", async () => {
    mockApi.getDocument.mockResolvedValueOnce({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "failed",
      page_count: 0,
      chunk_count: 0,
      checksum: "abc123",
      error_message: "Processing failed",
      error_details: {
        stage: "embedding",
        code: "EMBED_TIMEOUT",
        category: "transient",
        retryable: true,
        message: "Embedding provider timeout",
      },
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValueOnce({
      document_id: "doc-1",
      status: "failed",
      error_message: "Processing failed",
      error_details: {
        stage: "embedding",
        code: "EMBED_TIMEOUT",
        category: "transient",
        retryable: true,
        message: "Embedding provider timeout",
      },
      updated_at: "2026-05-15T10:00:00Z",
    });

    renderPage();

    expect(await screen.findByText("Processing error")).toBeInTheDocument();
    expect(screen.getByText("Processing failed")).toBeInTheDocument();
    expect(screen.getByText(/EMBED_TIMEOUT/)).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Ask in Chat" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ask in Chat")).toBeInTheDocument();
  });

  it("uses safe not-found behavior for inaccessible documents", async () => {
    mockApi.getDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 403,
        payload: { detail: "forbidden internal detail" },
      }),
    );

    renderPage();

    expect(await screen.findByText("Document not found")).toBeInTheDocument();
    expect(
      screen.queryByText("forbidden internal detail"),
    ).not.toBeInTheDocument();
  });

  it("keeps rendering document details when live status endpoint fails", async () => {
    mockApi.getDocumentStatus.mockRejectedValueOnce(
      normalizeApiError({
        status: 404,
        payload: { detail: "status endpoint unavailable" },
      }),
    );

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "policy.pdf" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Document not found")).not.toBeInTheDocument();
  });

  it("accepts a safe chat back-link from citation deep links", async () => {
    mockNavigation.searchParams = new URLSearchParams({
      back: "/chat",
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "policy.pdf" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to documents" }),
    ).toHaveAttribute("href", "/chat");
  });

  it("hides admin actions for viewer role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "viewer@example.com",
        role: "viewer",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "policy.pdf" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Re-index" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("More actions")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /include full chunk text/i }),
    ).not.toBeInTheDocument();
  });

  it("requires confirmation before delete and supports delete success flow", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    const confirmMock = vi.mocked(window.confirm);
    confirmMock.mockReturnValueOnce(false);
    await userEvent.click(screen.getByText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(mockApi.deleteDocument).not.toHaveBeenCalled();

    confirmMock.mockReturnValueOnce(true);
    await userEvent.click(screen.getByText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(mockApi.deleteDocument).toHaveBeenCalledWith("doc-1");
    });
    expect(
      await screen.findByText(/Delete requested\. Current status: deleting\./i),
    ).toBeInTheDocument();
  });

  it("shows conflict-safe messages for delete and re-index mutations", async () => {
    mockApi.deleteDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 409,
        payload: { detail: "cannot delete while processing" },
      }),
    );
    mockApi.reindexDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 409,
        payload: { detail: "cannot reindex while deleting" },
      }),
    );

    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    await userEvent.click(screen.getByText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(
      await screen.findByText(
        /cannot be deleted in its current lifecycle state/i,
      ),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Re-index" }));
    expect(
      await screen.findByText(
        /cannot be re-indexed in its current lifecycle state/i,
      ),
    ).toBeInTheDocument();
  });

  it("offers force re-index for documents stuck in processing", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "stuck.pdf",
      file_type: "pdf",
      status: "processing",
      page_count: 12,
      chunk_count: 120,
      checksum: "abc123",
      error_message: "indexing stalled",
      error_details: null,
      language: "en",
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValue({
      document_id: "doc-1",
      status: "processing",
      error_message: "indexing stalled",
      error_details: null,
      updated_at: "2026-05-15T10:00:00Z",
    });

    renderPage();

    await screen.findByRole("heading", { name: "stuck.pdf" });
    await userEvent.click(screen.getByText("More actions"));
    expect(screen.getByRole("button", { name: "Re-index" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Force re-index" }),
    ).toBeEnabled();

    await userEvent.click(
      screen.getByRole("button", { name: "Force re-index" }),
    );
    await waitFor(() => {
      expect(mockApi.reindexDocument).toHaveBeenCalledWith("doc-1", {
        force: true,
      });
    });
    expect(
      await screen.findByText(
        /Force re-index requested\. Queue status: queued\./i,
      ),
    ).toBeInTheDocument();
  });

  it("supports successful re-index mutation flow", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    await screen.findByRole("button", { name: "Queue re-index" });
    await userEvent.click(screen.getByText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Re-index" }));
    await waitFor(() => {
      expect(mockApi.reindexDocument).toHaveBeenCalledWith("doc-1", undefined);
    });
    expect(
      await screen.findByText(
        /Re-index requested using the system default profile\. Queue status: queued\./i,
      ),
    ).toBeInTheDocument();
  });

  it("queues a re-index with a selected organization profile", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    await screen.findByRole("button", { name: "Queue re-index" });
    await userEvent.selectOptions(
      screen.getAllByRole("combobox")[0],
      "profile-1",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Queue re-index" }),
    );

    await waitFor(() => {
      expect(mockApi.reindexDocument).toHaveBeenCalledWith("doc-1", {
        chunking_profile_id: "profile-1",
      });
    });
    expect(
      await screen.findByText(
        /Re-index requested using Operations Default\. Queue status: queued\./i,
      ),
    ).toBeInTheDocument();
  });

  it("shows detected language in the language panel", async () => {
    mockApi.getDocument.mockResolvedValue({
      ...mockApi.getDocument.mock.results[0]?.value,
      document_id: "doc-1",
      filename: "report.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 5,
      chunk_count: 40,
      language: "de",
      language_confidence: 0.85,
      language_source: "auto_detected",
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "report.pdf" });

    expect(screen.getByText("German")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("auto detected")).toBeInTheDocument();
  });

  it("shows language panel with dash when no language detected", async () => {
    mockApi.getDocument.mockResolvedValue({
      ...mockApi.getDocument.mock.results[0]?.value,
      document_id: "doc-1",
      filename: "unknown.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 1,
      chunk_count: 5,
      language: null,
      language_confidence: null,
      language_source: null,
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "unknown.pdf" });

    expect(screen.getByText("Language")).toBeInTheDocument();
    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
  });

  it("shows override button for admin and submits override", async () => {
    mockApi.getDocument.mockResolvedValue({
      ...mockApi.getDocument.mock.results[0]?.value,
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 5,
      chunk_count: 40,
      language: "en",
      language_confidence: 0.9,
      language_source: "auto_detected",
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    mockApi.overrideDocumentLanguage.mockResolvedValue({
      document_id: "doc-1",
      language: "fr",
      language_source: "admin_override",
      language_confidence: null,
      updated_at: "2026-06-01T00:02:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    const overrideBtn = await screen.findByRole("button", {
      name: "Override language",
    });
    await userEvent.click(overrideBtn);

    const select = screen.getByRole("combobox", {
      name: "Select override language",
    });
    await userEvent.selectOptions(select, "fr");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockApi.overrideDocumentLanguage).toHaveBeenCalledWith("doc-1", {
        language: "fr",
      });
    });
  });

  it("hides override button for viewer role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "viewer@example.com",
        role: "viewer",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };
    mockApi.getDocument.mockResolvedValue({
      ...mockApi.getDocument.mock.results[0]?.value,
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 5,
      chunk_count: 40,
      language: "en",
      language_confidence: null,
      language_source: null,
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "policy.pdf" });

    expect(
      screen.queryByRole("button", { name: "Override language" }),
    ).not.toBeInTheDocument();
  });

  it("shows OCR quality panel with avg confidence when quality snapshot present", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "scanned.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 5,
      chunk_count: 40,
      language: "de",
      language_confidence: null,
      language_source: null,
      ocr_languages_override: "deu",
      ocr_quality_snapshot: {
        status: "completed",
        mode: "scanned",
        languages: ["deu"],
        effective_languages_string: "deu",
        pages_processed: 5,
        pages_completed: 5,
        pages_failed: 0,
        duration_ms: 3100,
        avg_confidence: 0.82,
        page_confidences: [],
        warnings: [],
      },
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-04T00:00:00Z",
      updated_at: "2026-06-04T00:01:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "scanned.pdf" });

    expect(screen.getByText("OCR quality")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getAllByText("deu").length).toBeGreaterThan(0);
  });

  it("shows low confidence warning when OCR quality is below 30%", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "lowquality.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 2,
      chunk_count: 4,
      language: null,
      language_confidence: null,
      language_source: null,
      ocr_quality_snapshot: {
        status: "partial",
        mode: "mixed",
        languages: ["eng"],
        effective_languages_string: "eng",
        pages_processed: 2,
        pages_completed: 1,
        pages_failed: 0,
        duration_ms: 800,
        avg_confidence: 0.12,
        page_confidences: [],
        warnings: [],
      },
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-04T00:00:00Z",
      updated_at: "2026-06-04T00:01:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "lowquality.pdf" });

    expect(screen.getByText(/Low OCR confidence/i)).toBeInTheDocument();
  });

  it("shows admin Set OCR language button for admin role and submits", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "scanned.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 3,
      chunk_count: 20,
      language: null,
      language_confidence: null,
      language_source: null,
      ocr_quality_snapshot: {
        status: "completed",
        mode: "scanned",
        languages: ["eng"],
        effective_languages_string: "eng",
        pages_processed: 3,
        pages_completed: 3,
        pages_failed: 0,
        duration_ms: 1200,
        avg_confidence: 0.75,
        page_confidences: [],
        warnings: [],
      },
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-04T00:00:00Z",
      updated_at: "2026-06-04T00:01:00Z",
    });
    mockApi.configureDocumentOcr.mockResolvedValue({
      document_id: "doc-1",
      ocr_languages_override: "deu",
      ocr_quality_snapshot: null,
      updated_at: "2026-06-04T00:02:00Z",
    });
    renderPage();
    await screen.findByRole("heading", { name: "scanned.pdf" });

    const setOcrBtn = await screen.findByRole("button", {
      name: "Set OCR language",
    });
    await userEvent.click(setOcrBtn);

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Select OCR language" }),
      "de",
    );

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockApi.configureDocumentOcr).toHaveBeenCalledWith("doc-1", {
        ocr_languages: ["de"],
      });
    });
  });

  it("shows embedding provider type and vector dimension when set on the document", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 12,
      chunk_count: 120,
      checksum: "abc123",
      error_message: null,
      error_details: null,
      language: "en",
      embedding_provider_type: "local",
      embedding_vector_dimension: 768,
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    renderPage();

    await screen.findByRole("heading", { name: "policy.pdf" });
    expect(await screen.findByText("local")).toBeInTheDocument();
    expect(await screen.findByText("768")).toBeInTheDocument();
  });

  it("hides embedding provider rows when metadata is not yet set", async () => {
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "new.pdf",
      file_type: "pdf",
      status: "processing",
      page_count: null,
      chunk_count: 0,
      checksum: null,
      error_message: null,
      error_details: null,
      language: null,
      embedding_provider_type: null,
      embedding_vector_dimension: null,
      chunking_diagnostics: null,
      lifecycle_timeline: [],
      created_at: "2026-06-09T10:00:00Z",
      updated_at: "2026-06-09T10:00:00Z",
    });
    renderPage();

    await screen.findByRole("heading", { name: "new.pdf" });
    expect(screen.queryByText("Embedding provider")).not.toBeInTheDocument();
    expect(screen.queryByText("Vector dimension")).not.toBeInTheDocument();
  });
});
