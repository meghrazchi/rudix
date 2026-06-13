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
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ChatPage } from "@/components/chat/ChatPage";
import { listDocuments } from "@/lib/api/documents";

const apiBaseUrl = "http://api.test";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

const chatPayloads: Array<{
  chat_session_id: string | null;
  question: string;
  document_ids?: string[];
  top_k?: number;
  rerank?: boolean;
}> = [];

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: vi.fn(),
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
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-15T09:00:00Z",
          updated_at: "2026-05-15T09:10:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    }),
  ),
  http.get(`${apiBaseUrl}/collections`, async () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get(`${apiBaseUrl}/connectors/connections`, async () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.post(`${apiBaseUrl}/chat/sessions`, async () =>
    HttpResponse.json(
      {
        session_id: "session-new",
        title: null,
        message_count: 0,
        created_at: "2026-05-15T10:10:00Z",
        updated_at: "2026-05-15T10:10:00Z",
      },
      { status: 201 },
    ),
  ),
  http.post(`${apiBaseUrl}/chat`, async ({ request }) => {
    const payload = (await request.json()) as {
      chat_session_id?: string;
      question?: string;
      document_ids?: string[];
      top_k?: number;
      rerank?: boolean;
    };
    chatPayloads.push({
      chat_session_id: payload.chat_session_id ?? null,
      question: payload.question ?? "",
      document_ids: payload.document_ids,
      top_k: payload.top_k,
      rerank: payload.rerank,
    });
    return HttpResponse.json({
      chat_session_id: payload.chat_session_id ?? "session-new",
      message_id: "msg-1",
      answer: "MSW answer",
      confidence_score: 0.81,
      confidence_category: "high",
      confidence_explanation: {
        top_similarity: 0.8,
        average_similarity: 0.7,
        top_rerank_score: 0.75,
        citation_support_score: 0.7,
        citation_validation_score: 0.9,
        citation_coverage_score: 0.85,
        retrieval_agreement_score: 0.8,
        raw_score: 0.81,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      debug: {
        latencies_ms: { total: 110 },
        retrieval_count: 3,
        selected_count: 2,
        rerank_applied: true,
        embedding_model: "embed-model",
        llm_model: "llm-model",
      },
      created_at: "2026-05-15T10:12:00Z",
    });
  }),
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

async function openAdditionalSettings() {
  await userEvent.click(
    await screen.findByRole("button", { name: /Additional settings/i }),
  );
}

async function openScopeMenu() {
  await userEvent.click(
    await screen.findByRole("button", { name: /Select scope/i }),
  );
  return screen.findByRole("menu", { name: /Select scope/i });
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
  chatPayloads.length = 0;
  window.localStorage.clear();
  vi.mocked(listDocuments).mockResolvedValue({
    items: [
      {
        document_id: "doc-indexed-1",
        filename: "indexed.pdf",
        file_type: "pdf",
        status: "indexed",
        page_count: 1,
        chunk_count: 5,
        error_message: null,
        error_details: null,
        created_at: "2026-05-15T09:00:00Z",
        updated_at: "2026-05-15T09:10:00Z",
      },
    ],
    total: 1,
    limit: 200,
    offset: 0,
    status: "indexed",
    sort_by: "updated_at",
    sort_order: "desc",
  });
  Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: vi.fn(),
  });
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
        HttpResponse.json({ detail: "service down" }, { status: 503 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/The service is temporarily unavailable/i),
    ).toBeInTheDocument();
  });

  it.skip("submits a new question and renders the successful response", async () => {
    renderPage();

    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
    await userEvent.type(textarea, "When did it start?");
    fireEvent.submit(textarea.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(chatPayloads.length).toBe(1);
    });
    expect(chatPayloads[0]?.chat_session_id).toBe("session-new");
    expect(chatPayloads[0]?.question).toBe("When did it start?");
  });

  it("sends selected document_ids with top_k and rerank in chat payload", async () => {
    renderPage();

    const scopeMenu = await openScopeMenu();
    await userEvent.click(
      within(scopeMenu).getByRole("button", { name: /All documents/i }),
    );
    await userEvent.click(
      within(scopeMenu).getByRole("button", { name: /Select documents/i }),
    );
    await userEvent.click(
      within(scopeMenu).getByRole("button", { name: /indexed\.pdf/i }),
    );

    await openAdditionalSettings();
    const topKInput = screen.getByRole("slider", { name: /Top-k/i });
    fireEvent.change(topKInput, { target: { value: "8" } });
    await userEvent.click(screen.getByRole("checkbox", { name: /Rerank/i }));

    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
    await userEvent.type(textarea, "Send payload");
    fireEvent.submit(textarea.closest("form") as HTMLFormElement);

    expect(await screen.findByText("MSW answer")).toBeInTheDocument();
    expect(chatPayloads.length).toBe(1);
    expect(chatPayloads[0]).toMatchObject({
      chat_session_id: "session-new",
      question: "Send payload",
      document_ids: ["doc-indexed-1"],
      top_k: 8,
      rerank: false,
    });
  });

  it("preserves the draft question when submission fails", async () => {
    server.use(
      http.post(`${apiBaseUrl}/chat`, async () =>
        HttpResponse.json({ detail: "upstream timeout" }, { status: 503 }),
      ),
    );

    renderPage();

    await screen.findByRole("button", { name: /Context \([1-9]/i });
    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
    await userEvent.type(textarea, "Keep this draft");
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText("Unable to complete the query."),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Keep this draft")).toBeInTheDocument();
  });
});
