import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminTaxonomyPage } from "@/components/admin/AdminTaxonomyPage";
import type {
  MetadataFieldListResponse,
  MetadataFieldResponse,
} from "@/lib/api/metadata";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listMetadataFields: vi.fn(),
  createMetadataField: vi.fn(),
  updateMetadataField: vi.fn(),
  deleteMetadataField: vi.fn(),
}));

const mockPermissions = vi.hoisted(() => ({
  isAdmin: true,
  isOwner: false,
  isMember: false,
  isViewer: false,
  hasPermission: () => true,
}));

vi.mock("@/lib/api/metadata", () => ({
  listMetadataFields: (inactive?: boolean) =>
    mockApi.listMetadataFields(inactive),
  createMetadataField: (payload: unknown) =>
    mockApi.createMetadataField(payload),
  updateMetadataField: (id: string, payload: unknown) =>
    mockApi.updateMetadataField(id, payload),
  deleteMetadataField: (id: string) => mockApi.deleteMetadataField(id),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
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

function makeField(
  overrides: Partial<MetadataFieldResponse> = {},
): MetadataFieldResponse {
  return {
    field_id: "field-1",
    organization_id: "org-1",
    name: "department",
    display_name: "Department",
    field_type: "text",
    allowed_values: null,
    is_required: false,
    is_filterable: true,
    description: null,
    sort_order: 0,
    is_active: true,
    created_at: "2026-06-25T10:00:00Z",
    updated_at: "2026-06-25T10:00:00Z",
    ...overrides,
  };
}

function makeList(
  fields: MetadataFieldResponse[] = [],
): MetadataFieldListResponse {
  return { items: fields, total: fields.length };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminTaxonomyPage />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AdminTaxonomyPage", () => {
  beforeEach(() => {
    mockApi.listMetadataFields.mockReset();
    mockApi.createMetadataField.mockReset();
    mockApi.updateMetadataField.mockReset();
    mockApi.deleteMetadataField.mockReset();
    mockPermissions.isAdmin = true;
  });

  it("shows empty state when no fields defined", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList());
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/no metadata fields defined/i),
      ).toBeInTheDocument();
    });
  });

  it("renders table with field rows", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList([makeField()]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("department")).toBeInTheDocument();
      expect(screen.getByText("Department")).toBeInTheDocument();
    });
  });

  it("shows FieldTypeChip for field type", async () => {
    mockApi.listMetadataFields.mockResolvedValue(
      makeList([
        makeField({
          field_type: "select",
          name: "region",
          display_name: "Region",
        }),
      ]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Select")).toBeInTheDocument();
    });
  });

  it("shows create form on Add field click", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no metadata fields/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /add field/i }));
    expect(screen.getByText("New metadata field")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/e.g. department/i)).toBeInTheDocument();
  });

  it("submits create form and shows new field", async () => {
    mockApi.listMetadataFields
      .mockResolvedValueOnce(makeList())
      .mockResolvedValue(makeList([makeField()]));
    mockApi.createMetadataField.mockResolvedValue(makeField());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no metadata fields/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /add field/i }));

    fireEvent.change(screen.getByPlaceholderText(/e.g. department/i), {
      target: { value: "department" },
    });
    fireEvent.change(screen.getByPlaceholderText(/e.g. Department/i), {
      target: { value: "Department" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create field/i }));

    await waitFor(() => {
      expect(mockApi.createMetadataField).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "department",
          display_name: "Department",
        }),
      );
    });
  });

  it("shows edit form with pre-filled display_name", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList([makeField()]));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Department")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    const input = screen.getByPlaceholderText(
      /e.g. Department/i,
    ) as HTMLInputElement;
    expect(input.value).toBe("Department");
  });

  it("calls updateMetadataField on save", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList([makeField()]));
    mockApi.updateMetadataField.mockResolvedValue(
      makeField({ display_name: "Business Unit" }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Department")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));

    const input = screen.getByPlaceholderText(/e.g. Department/i);
    fireEvent.change(input, { target: { value: "Business Unit" } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(mockApi.updateMetadataField).toHaveBeenCalledWith(
        "field-1",
        expect.objectContaining({ display_name: "Business Unit" }),
      );
    });
  });

  it("opens delete confirmation dialog", async () => {
    mockApi.listMetadataFields.mockResolvedValue(makeList([makeField()]));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Department")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(screen.getByText(/delete field\?/i)).toBeInTheDocument();
  });

  it("calls deleteMetadataField on confirm", async () => {
    mockApi.listMetadataFields
      .mockResolvedValueOnce(makeList([makeField()]))
      .mockResolvedValue(makeList());
    mockApi.deleteMetadataField.mockResolvedValue(undefined);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Department")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    const confirmBtn = screen.getByRole("button", {
      name: /^delete$/i,
      hidden: false,
    });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi.deleteMetadataField).toHaveBeenCalledWith("field-1");
    });
  });

  it("shows forbidden state for non-admin", async () => {
    mockPermissions.isAdmin = false;
    mockApi.listMetadataFields.mockResolvedValue(makeList());
    renderPage();
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /add field/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("shows inactive fields when toggle enabled", async () => {
    const inactive = makeField({ is_active: false, display_name: "OldField" });
    mockApi.listMetadataFields.mockResolvedValue(makeList([inactive]));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no metadata fields/i)).toBeInTheDocument(),
    );
    // Toggle show inactive
    const toggle = screen.getByRole("checkbox", { name: /show inactive/i });
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });
  });
});
