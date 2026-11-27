import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  AdminVectorIndexPage,
  VECTOR_INDEX_POLL_MS,
  vectorIndexRefetchInterval,
} from "@/components/admin/AdminVectorIndexPage";
import { normalizeApiError } from "@/lib/api/errors";
import {
  progressFraction,
  type VectorIndexStatus,
} from "@/lib/api/vector-index";
import type { SessionState } from "@/lib/auth-session";

const mocks = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
  getVectorIndexStatus: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mocks.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/vector-index", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/vector-index")>();
  return { ...actual, getVectorIndexStatus: mocks.getVectorIndexStatus };
});

function session(role: string): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "user@example.com",
      role,
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token",
    },
  } as SessionState;
}

function apiError(status: number, requestId: string | null = null) {
  return normalizeApiError({ status, payload: null, requestId });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AdminVectorIndexPage />
    </QueryClientProvider>,
  );
}

const BUILDING: VectorIndexStatus = {
  alias: "rudix_live",
  legacy_mode: false,
  active: {
    generation: 1,
    embedding_model: "text-embedding-3-small",
    vector_size: 1536,
    activated_at: "2026-11-01T00:00:00Z",
  },
  building: {
    generation: 2,
    embedding_model: "text-embedding-3-large",
    state: "building",
    started_at: "2026-11-27T10:00:00Z",
  },
  progress: { documents_total: 8, documents_done: 2 },
};

beforeEach(() => {
  mocks.getVectorIndexStatus.mockReset();
  mocks.authState = session("admin");
});

describe("AdminVectorIndexPage", () => {
  it("shows the active model and the organisation's build progress", async () => {
    mocks.getVectorIndexStatus.mockResolvedValue(BUILDING);
    renderPage();

    await screen.findByText("text-embedding-3-small");
    expect(screen.getByText("text-embedding-3-large")).toBeInTheDocument();
    expect(screen.getByText("2 of 8 (25%)")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "25",
    );
    expect(screen.getByText("Building")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows the legacy-mode notice and no rebuild", async () => {
    mocks.getVectorIndexStatus.mockResolvedValue({
      alias: null,
      legacy_mode: true,
      active: {
        generation: null,
        embedding_model: "text-embedding-3-small",
        vector_size: 1536,
        activated_at: null,
      },
      building: null,
      progress: null,
    });
    renderPage();

    await screen.findByRole("note");
    expect(screen.getByText("Not versioned")).toBeInTheDocument();
    expect(screen.getByText("No rebuild running")).toBeInTheDocument();
  });

  it("shows the not-adopted empty state", async () => {
    mocks.getVectorIndexStatus.mockResolvedValue({
      alias: "rudix_live",
      legacy_mode: false,
      active: null,
      building: null,
      progress: null,
    });
    renderPage();

    await screen.findByText("No active generation yet");
  });

  it("shows a loading state first", () => {
    mocks.getVectorIndexStatus.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(
      screen.getByText("Loading vector index status..."),
    ).toBeInTheDocument();
  });

  it("shows an error with the request id and retries", async () => {
    const user = userEvent.setup();
    mocks.getVectorIndexStatus
      .mockRejectedValueOnce(apiError(500, "req-123"))
      .mockResolvedValueOnce(BUILDING);
    renderPage();

    await screen.findByText("Unable to load the vector index status");
    expect(screen.getByText("req-123")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("text-embedding-3-small");
  });

  it("shows the rate-limit state on 429", async () => {
    mocks.getVectorIndexStatus.mockRejectedValue(apiError(429, "req-429"));
    renderPage();

    await screen.findByLabelText("Rate limit state");
    expect(screen.getByText("req-429")).toBeInTheDocument();
  });

  it("shows the forbidden state when the API returns 403", async () => {
    mocks.getVectorIndexStatus.mockRejectedValue(apiError(403));
    renderPage();

    await screen.findByText("Admin access restricted");
  });

  it("never requests the status for lower roles", async () => {
    mocks.authState = session("member");
    renderPage();

    await screen.findByText("Admin access restricted");
    expect(mocks.getVectorIndexStatus).not.toHaveBeenCalled();
  });

  it("polls only while a generation is building", () => {
    expect(vectorIndexRefetchInterval(BUILDING)).toBe(VECTOR_INDEX_POLL_MS);
    expect(vectorIndexRefetchInterval({ ...BUILDING, building: null })).toBe(
      false,
    );
    expect(vectorIndexRefetchInterval(undefined)).toBe(false);
  });

  it("computes the progress fraction safely", () => {
    expect(progressFraction(null)).toBe(0);
    expect(progressFraction({ documents_total: 0, documents_done: 0 })).toBe(0);
    expect(progressFraction({ documents_total: 4, documents_done: 9 })).toBe(1);
  });
});
