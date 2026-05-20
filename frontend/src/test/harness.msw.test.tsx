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

import { useQuery } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { useSearchParams } from "next/navigation";

import { listChatSessions } from "@/lib/api/chat";
import { listDocuments } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";
import { createMockApiServer } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams("status=indexed"),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const server = createMockApiServer();

function HarnessProbe() {
  const searchParams = useSearchParams();
  const status = searchParams.get("status") ?? undefined;
  const documentsQuery = useQuery({
    queryKey: ["probe", "documents", status],
    queryFn: () =>
      listDocuments({
        status: status as "indexed" | undefined,
        limit: 20,
        offset: 0,
      }),
  });
  const sessionsQuery = useQuery({
    queryKey: ["probe", "chat-sessions"],
    queryFn: () => listChatSessions({ limit: 50, offset: 0 }),
  });

  if (documentsQuery.isLoading || sessionsQuery.isLoading) {
    return <p>Loading harness...</p>;
  }

  if (documentsQuery.isError || sessionsQuery.isError) {
    return <p>Harness error</p>;
  }

  return (
    <div>
      <p>Documents total: {documentsQuery.data?.total ?? 0}</p>
      <p>Sessions total: {sessionsQuery.data?.total ?? 0}</p>
      <p>Filter: {status ?? "none"}</p>
    </div>
  );
}

describe("test harness with shared MSW fixtures", () => {
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
    process.env.NEXT_PUBLIC_API_URL = "http://api.test";
    mockNavigation.searchParams = new URLSearchParams("status=indexed");
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "admin-user",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };
  });

  it("loads stable fixtures with renderWithProviders and shared handlers", async () => {
    renderWithProviders(<HarnessProbe />);

    expect(await screen.findByText("Documents total: 1")).toBeInTheDocument();
    expect(await screen.findByText("Sessions total: 1")).toBeInTheDocument();
    expect(await screen.findByText("Filter: indexed")).toBeInTheDocument();
  });

  it("can still render with plain React Testing Library when needed", async () => {
    const { queryClient } = renderWithProviders(<HarnessProbe />);

    expect(await screen.findByText("Documents total: 1")).toBeInTheDocument();
    queryClient.clear();
    render(<div>secondary render path</div>);
    expect(screen.getByText("secondary render path")).toBeInTheDocument();
  });
});
