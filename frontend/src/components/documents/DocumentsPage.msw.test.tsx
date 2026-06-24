import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { SessionState } from "@/lib/auth-session";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const listDocumentsResponse = {
  items: [
    {
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 3,
      chunk_count: 12,
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T00:00:00Z",
      updated_at: "2026-05-14T00:00:00Z",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  status: null,
  sort_by: "created_at",
  sort_order: "desc",
};

const server = setupServer(
  http.get(`${apiBaseUrl}/documents`, async () =>
    HttpResponse.json(listDocumentsResponse),
  ),
  http.get(`${apiBaseUrl}/documents/:documentId`, async ({ params }) =>
    HttpResponse.json({
      document_id: String(params.documentId),
      filename: "guide.pdf",
      file_type: "pdf",
      status: "uploaded",
      page_count: 1,
      chunk_count: 0,
      checksum: "xyz",
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T00:00:00Z",
      updated_at: "2026-05-14T00:00:00Z",
    }),
  ),
  http.get(`${apiBaseUrl}/documents/:documentId/status`, async ({ params }) =>
    HttpResponse.json({
      document_id: String(params.documentId),
      status: "uploaded",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-14T00:00:00Z",
    }),
  ),
  http.get(`${apiBaseUrl}/documents/:documentId/chunks`, async ({ params }) =>
    HttpResponse.json({
      document_id: String(params.documentId),
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
      include_full_text: false,
    }),
  ),
  http.post(`${apiBaseUrl}/documents/upload`, async () =>
    HttpResponse.json(
      {
        document_id: "doc-2",
        filename: "guide.pdf",
        status: "uploaded",
        queue_status: "queued",
        checksum: "xyz",
        message: "Document uploaded and queued for processing.",
      },
      { status: 201 },
    ),
  ),
);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentsPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  mockNavigation.searchParams = new URLSearchParams();
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "u-1",
      email: "member@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("DocumentsPage upload states (MSW)", () => {
  it("shows queued/success state after successful upload", async () => {
    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(
      screen.getByRole("button", {
        name: /Upload Documents|Open upload modal/i,
      }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(
        screen.getAllByText(
          /Uploaded 1\/1 file\(s\)\. Processing has been queued\./i,
        ).length,
      ).toBeGreaterThan(0);
    });
  });

  it("shows safe 413 error message", async () => {
    server.use(
      http.post(`${apiBaseUrl}/documents/upload`, async () =>
        HttpResponse.json({ detail: "File too large" }, { status: 413 }),
      ),
    );

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.click(
      screen.getByRole("button", {
        name: /Upload Documents|Open upload modal/i,
      }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(
        screen.getAllByText(/uploaded file is too large/i).length,
      ).toBeGreaterThan(0);
    });
  });

  it("shows safe 415 error message", async () => {
    server.use(
      http.post(`${apiBaseUrl}/documents/upload`, async () =>
        HttpResponse.json(
          { detail: "Unsupported media type" },
          { status: 415 },
        ),
      ),
    );

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.click(
      screen.getByRole("button", {
        name: /Upload Documents|Open upload modal/i,
      }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(
        screen.getAllByText(/file type is not supported/i).length,
      ).toBeGreaterThan(0);
    });
  });
});

describe("DocumentsPage filters/sorting/pagination (MSW)", () => {
  it("sends filter and sort query params and preserves them across pagination", async () => {
    const observed: Array<{
      status: string | null;
      sortBy: string | null;
      sortOrder: string | null;
      limit: string | null;
      offset: string | null;
    }> = [];

    server.use(
      http.get(`${apiBaseUrl}/documents`, async ({ request }) => {
        const url = new URL(request.url);
        const limit = Number.parseInt(
          url.searchParams.get("limit") ?? "20",
          10,
        );
        const offset = Number.parseInt(
          url.searchParams.get("offset") ?? "0",
          10,
        );
        observed.push({
          status: url.searchParams.get("status"),
          sortBy: url.searchParams.get("sort_by"),
          sortOrder: url.searchParams.get("sort_order"),
          limit: url.searchParams.get("limit"),
          offset: url.searchParams.get("offset"),
        });

        const items = Array.from({ length: limit }, (_, index) => {
          const rowNumber = offset + index + 1;
          return {
            document_id: `doc-${rowNumber}`,
            filename: `file-${rowNumber}.pdf`,
            file_type: "pdf",
            status: "indexed",
            page_count: 1,
            chunk_count: 2,
            error_message: null,
            error_details: null,
            created_at: "2026-05-14T00:00:00Z",
            updated_at: "2026-05-15T00:00:00Z",
          };
        });

        return HttpResponse.json({
          items,
          total: 45,
          limit,
          offset,
          status: url.searchParams.get("status"),
          sort_by: url.searchParams.get("sort_by") ?? "created_at",
          sort_order: url.searchParams.get("sort_order") ?? "desc",
        });
      }),
    );

    renderPage();
    expect(await screen.findByText("file-1.pdf")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    await waitFor(() => {
      expect(
        observed.some(
          (entry) => entry.status === "failed" && entry.offset === "0",
        ),
      ).toBe(true);
    });

    await userEvent.selectOptions(screen.getByLabelText("Sort"), "updated_at");
    await waitFor(() => {
      expect(
        observed.some(
          (entry) =>
            entry.status === "failed" &&
            entry.sortBy === "updated_at" &&
            entry.offset === "0",
        ),
      ).toBe(true);
    });

    await userEvent.selectOptions(screen.getByLabelText("Order"), "asc");
    await waitFor(() => {
      expect(
        observed.some(
          (entry) =>
            entry.status === "failed" &&
            entry.sortBy === "updated_at" &&
            entry.sortOrder === "asc" &&
            entry.offset === "0",
        ),
      ).toBe(true);
    });

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(
        observed.some(
          (entry) =>
            entry.status === "failed" &&
            entry.sortBy === "updated_at" &&
            entry.sortOrder === "asc" &&
            entry.limit === "20" &&
            entry.offset === "20",
        ),
      ).toBe(true);
    });
  });
});
