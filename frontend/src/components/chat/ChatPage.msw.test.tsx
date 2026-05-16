import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ChatPage } from "@/components/chat/ChatPage";

const apiBaseUrl = "http://api.test";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const server = setupServer(
  http.get(`${apiBaseUrl}/chat/sessions`, async ({ request }) => {
    const url = new URL(request.url);
    const offset = Number.parseInt(url.searchParams.get("offset") ?? "0", 10);
    if (offset === 0) {
      await delay(120);
      return HttpResponse.json({
        items: [
          {
            session_id: "session-1",
            title: "MSW Session",
            message_count: 2,
            created_at: "2026-05-15T10:00:00Z",
            updated_at: "2026-05-15T10:05:00Z",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
    }
    return HttpResponse.json({ items: [], total: 1, limit: 50, offset });
  }),
  http.get(`${apiBaseUrl}/documents`, async () =>
    HttpResponse.json({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    })),
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
      <ChatPage />
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
  mockNavigation.searchParams = new URLSearchParams();
});

describe("ChatPage sessions (MSW)", () => {
  it("shows loading state and then renders sessions", async () => {
    renderPage();

    expect(screen.getByText("Loading sessions...")).toBeInTheDocument();
    expect(await screen.findByText("MSW Session")).toBeInTheDocument();
  });

  it("shows session list error state", async () => {
    server.use(
      http.get(`${apiBaseUrl}/chat/sessions`, async () =>
        HttpResponse.json({ detail: "service down" }, { status: 503 })),
    );

    renderPage();

    expect(await screen.findByText(/The service is temporarily unavailable/i)).toBeInTheDocument();
  });
});

