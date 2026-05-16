import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { SessionState } from "@/lib/auth-session";

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
  http.get(`${apiBaseUrl}/documents`, async () => HttpResponse.json(listDocumentsResponse)),
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
    )),
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

    await userEvent.click(screen.getByRole("button", { name: "Open upload modal" }));

    const uploadInput = screen.getByRole("dialog").querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(screen.getByText(/queued successfully/i)).toBeInTheDocument();
    });
  });

  it("shows safe 413 error message", async () => {
    server.use(
      http.post(`${apiBaseUrl}/documents/upload`, async () =>
        HttpResponse.json({ detail: "File too large" }, { status: 413 })),
    );

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Open upload modal" }));

    const uploadInput = screen.getByRole("dialog").querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(screen.getAllByText(/uploaded file is too large/i).length).toBeGreaterThan(0);
    });
  });

  it("shows safe 415 error message", async () => {
    server.use(
      http.post(`${apiBaseUrl}/documents/upload`, async () =>
        HttpResponse.json({ detail: "Unsupported media type" }, { status: 415 })),
    );

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Open upload modal" }));

    const uploadInput = screen.getByRole("dialog").querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(screen.getAllByText(/file type is not supported/i).length).toBeGreaterThan(0);
    });
  });
});
