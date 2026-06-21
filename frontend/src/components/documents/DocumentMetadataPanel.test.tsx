import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentMetadataPanel } from "@/components/documents/DocumentMetadataPanel";
import type {
  DocumentMetadataResponse,
  MetadataFieldListResponse,
  MetadataFieldResponse,
} from "@/lib/api/metadata";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listMetadataFields: vi.fn(),
  getDocumentMetadata: vi.fn(),
  setDocumentMetadata: vi.fn(),
  suggestTagValues: vi.fn(),
  getDocumentMetadataAudit: vi.fn(),
}));

vi.mock("@/lib/api/metadata", () => ({
  listMetadataFields: (inactive?: boolean) =>
    mockApi.listMetadataFields(inactive),
  getDocumentMetadata: (id: string) => mockApi.getDocumentMetadata(id),
  setDocumentMetadata: (id: string, payload: unknown) =>
    mockApi.setDocumentMetadata(id, payload),
  suggestTagValues: (fieldId: string, prefix: string) =>
    mockApi.suggestTagValues(fieldId, prefix),
  getDocumentMetadataAudit: (id: string, opts?: unknown) =>
    mockApi.getDocumentMetadataAudit(id, opts),
}));

vi.mock("@/lib/api/errors", () => ({
  getApiErrorMessage: (err: unknown) =>
    err instanceof Error ? err.message : "Error",
}));

vi.mock("@/lib/api/query", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/query")>();
  return {
    ...real,
    invalidateAfterMutation: vi.fn().mockResolvedValue(undefined),
  };
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeTextField(
  overrides: Partial<MetadataFieldResponse> = {},
): MetadataFieldResponse {
  return {
    field_id: "field-text",
    organization_id: "org-1",
    name: "department",
    display_name: "Department",
    field_type: "text",
    allowed_values: null,
    is_required: false,
    is_filterable: true,
    description: "Which department owns this document",
    sort_order: 0,
    is_active: true,
    created_at: "2026-06-25T10:00:00Z",
    updated_at: "2026-06-25T10:00:00Z",
    ...overrides,
  };
}

function makeSelectField(): MetadataFieldResponse {
  return {
    field_id: "field-select",
    organization_id: "org-1",
    name: "region",
    display_name: "Region",
    field_type: "select",
    allowed_values: ["EMEA", "APAC", "Americas"],
    is_required: true,
    is_filterable: true,
    description: null,
    sort_order: 1,
    is_active: true,
    created_at: "2026-06-25T10:00:00Z",
    updated_at: "2026-06-25T10:00:00Z",
  };
}

function makeFieldList(
  fields: MetadataFieldResponse[] = [],
): MetadataFieldListResponse {
  return { items: fields, total: fields.length };
}

function makeDocMeta(
  documentId = "doc-1",
): DocumentMetadataResponse {
  return {
    document_id: documentId,
    values: [
      {
        field_id: "field-text",
        field_name: "department",
        display_name: "Department",
        field_type: "text",
        value: "Engineering",
        updated_at: "2026-06-25T10:00:00Z",
      },
    ],
  };
}

function renderPanel(canEdit = true, documentId = "doc-1") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentMetadataPanel documentId={documentId} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("DocumentMetadataPanel", () => {
  beforeEach(() => {
    mockApi.listMetadataFields.mockReset();
    mockApi.getDocumentMetadata.mockReset();
    mockApi.setDocumentMetadata.mockReset();
    mockApi.suggestTagValues.mockReset();
    mockApi.getDocumentMetadataAudit.mockReset();
  });

  it("shows empty hint when no fields defined", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeFieldList());
    mockApi.getDocumentMetadata.mockResolvedValue({
      document_id: "doc-1",
      values: [],
    });
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByText(/no metadata fields defined/i),
      ).toBeInTheDocument();
    });
  });

  it("renders field labels and current values in read mode", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Department")).toBeInTheDocument();
      expect(screen.getByText("Engineering")).toBeInTheDocument();
    });
  });

  it("shows '—' for fields with no value", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue({
      document_id: "doc-1",
      values: [],
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    });
  });

  it("shows Edit button when canEdit=true", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel(true);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    });
  });

  it("hides Edit button when canEdit=false", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel(false);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /^edit$/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("entering edit mode shows text input for text field", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    const inputs = screen.getAllByRole("textbox");
    expect(inputs.length).toBeGreaterThan(0);
  });

  it("cancel button exits edit mode", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    });
  });

  it("save calls setDocumentMetadata", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata
      .mockResolvedValueOnce(makeDocMeta())
      .mockResolvedValue(makeDocMeta());
    mockApi.setDocumentMetadata.mockResolvedValue(makeDocMeta());
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));

    // Change text value
    const input = screen.getAllByRole("textbox")[0];
    fireEvent.change(input, { target: { value: "Legal" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mockApi.setDocumentMetadata).toHaveBeenCalledWith(
        "doc-1",
        expect.objectContaining({
          values: expect.arrayContaining([
            expect.objectContaining({ field_id: "field-text" }),
          ]),
        }),
      );
    });
  });

  it("renders select field as dropdown in edit mode", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeSelectField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue({
      document_id: "doc-1",
      values: [],
    });
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toContain("EMEA");
  });

  it("shows audit log when toggle clicked", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    mockApi.getDocumentMetadataAudit.mockResolvedValue({
      items: [
        {
          audit_id: "a1",
          document_id: "doc-1",
          field_id: "field-text",
          field_name: "department",
          changed_by_id: "user-1",
          old_value: null,
          new_value: "Engineering",
          action: "set",
          created_at: "2026-06-25T10:00:00Z",
        },
      ],
      total: 1,
    });
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByText(/show audit log/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText(/show audit log/i));
    await waitFor(() => {
      expect(screen.getByText("Engineering")).toBeInTheDocument();
    });
  });

  it("hides audit log when toggle clicked again", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeFieldList([makeTextField()]),
    );
    mockApi.getDocumentMetadata.mockResolvedValue(makeDocMeta());
    mockApi.getDocumentMetadataAudit.mockResolvedValue({ items: [], total: 0 });
    renderPanel(true);
    await waitFor(() =>
      expect(screen.getByText(/show audit log/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText(/show audit log/i));
    await waitFor(() =>
      expect(screen.getByText(/hide audit log/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText(/hide audit log/i));
    await waitFor(() => {
      expect(screen.getByText(/show audit log/i)).toBeInTheDocument();
    });
  });
});
