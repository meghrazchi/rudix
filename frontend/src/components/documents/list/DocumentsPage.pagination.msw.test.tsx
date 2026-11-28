import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  onTestFinished,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { SessionState } from "@/lib/auth-session";
import { createPagedListHandlers } from "@/test/msw/handlers";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

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

const apiBaseUrl = "http://api.test";
const requests: URL[] = [];
const deleted: string[] = [];

const server = setupServer(
  ...createPagedListHandlers({ apiBaseUrl, requests }),
  http.delete(`${apiBaseUrl}/documents/:documentId`, ({ params }) => {
    deleted.push(String(params.documentId));
    return HttpResponse.json({
      document_id: String(params.documentId),
      status: "deleting",
    });
  }),
  http.get(`${apiBaseUrl}/documents/:documentId/collections`, () =>
    HttpResponse.json({ items: [] }),
  ),
);

function tableListRequests(): URL[] {
  return requests.filter(
    (url) =>
      url.pathname === "/documents" &&
      url.searchParams.get("limit") === "20" &&
      !url.searchParams.get("status"),
  );
}

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
  requests.length = 0;
  deleted.length = 0;
  vi.unstubAllEnvs();
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
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("DocumentsPage cursor pagination (MSW)", () => {
  it("shows the count and appends the next cursor page on load more", async () => {
    renderPage();

    expect(await screen.findByText("paged-1.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Showing 20 of 30")).toBeInTheDocument();
    expect(screen.queryByText("paged-21.pdf")).not.toBeInTheDocument();

    const first = tableListRequests()[0];
    expect(first?.searchParams.get("include_total")).toBe("true");
    expect(first?.searchParams.get("cursor")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("paged-30.pdf")).toBeInTheDocument();
    expect(screen.getByText("paged-1.pdf")).toBeInTheDocument();
    expect(screen.getByText("Showing 30 of 30")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();

    const cursorRequest = tableListRequests().find((url) =>
      url.searchParams.get("cursor"),
    );
    expect(cursorRequest?.searchParams.get("cursor")).toBe("msw-offset:20");
    expect(cursorRequest?.searchParams.get("include_total")).toBeNull();
    expect(cursorRequest?.searchParams.get("offset")).toBeNull();
  });

  it("keeps offset pages for other sorts", async () => {
    mockNavigation.searchParams = new URLSearchParams("sort_by=filename");
    renderPage();

    expect(await screen.findByText("paged-1.pdf")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(
        tableListRequests().some(
          (url) =>
            url.searchParams.get("offset") === "20" &&
            url.searchParams.get("sort_by") === "filename",
        ),
      ).toBe(true),
    );
  });

  it("virtualises rows above the threshold and keeps table semantics", async () => {
    vi.stubEnv("NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS", "5");
    // jsdom has no layout: give the scroll container a 320 px viewport so the
    // virtualiser computes a visible range (rows keep the 64 px estimate).
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "offsetHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get: () => 320,
    });
    onTestFinished(() => {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "offsetHeight", original);
      }
    });
    renderPage();

    const container = await screen.findByTestId("documents-table-virtual");
    const table = within(container).getByRole("table");
    expect(table).toHaveAttribute("aria-rowcount", "21");
    const header = within(table).getAllByRole("row")[0];
    expect(header).toHaveAttribute("aria-rowindex", "1");

    const bodyRows = within(table)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-index"));
    expect(bodyRows.length).toBeGreaterThan(0);
    expect(bodyRows.length).toBeLessThan(20);
    expect(bodyRows[0]).toHaveAttribute("aria-rowindex", "2");
  });

  it("refetches the loaded pages after a delete", async () => {
    renderPage();
    expect(await screen.findByText("paged-1.pdf")).toBeInTheDocument();
    const before = tableListRequests().length;

    const row = screen.getByText("paged-1.pdf").closest("tr");
    expect(row).not.toBeNull();
    await userEvent.click(
      within(row as HTMLElement).getByRole("button", { name: "Delete" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() => expect(deleted).toEqual(["paged-doc-1"]));
    await waitFor(() =>
      expect(tableListRequests().length).toBeGreaterThan(before),
    );
  });

  it("searches collections on the server in the assign dialog", async () => {
    renderPage();
    expect(await screen.findByText("paged-1.pdf")).toBeInTheDocument();

    const row = screen.getByText("paged-1.pdf").closest("tr");
    await userEvent.click(
      within(row as HTMLElement).getByRole("button", {
        name: "Assign to collections",
      }),
    );

    expect(await screen.findByText("Collection 1")).toBeInTheDocument();
    expect(screen.getByText("Showing 30 of 30")).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText("Search: Assign to Collections"),
      "Collection 7",
    );
    await waitFor(() =>
      expect(
        requests.some(
          (url) =>
            url.pathname === "/collections" &&
            url.searchParams.get("name_query") === "Collection 7",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("Showing 1 of 1")).toBeInTheDocument();
  });
});
