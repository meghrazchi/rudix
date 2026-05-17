import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { RagPipelinePage } from "@/components/pipeline/RagPipelinePage";
import { clearSessionStorage, writeSessionToStorage } from "@/lib/auth-session";

vi.mock("@xyflow/react", () => {
  const ReactFlow = ({
    nodes,
    onNodeClick,
    children,
  }: {
    nodes: Array<{ id: string; data: { label: string } }>;
    onNodeClick?: (_event: unknown, node: { id: string; data: { label: string } }) => void;
    children?: ReactNode;
  }) => (
    <div data-testid="react-flow">
      {nodes.map((node) => (
        <button key={node.id} type="button" onClick={() => onNodeClick?.({}, node)}>
          {node.data.label}
        </button>
      ))}
      {children}
    </div>
  );

  return {
    ReactFlow,
    ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Handle: () => null,
    MarkerType: { ArrowClosed: "ArrowClosed" },
    Position: { Left: "left", Right: "right" },
  };
});

const apiBaseUrl = "http://api.test";
let observedAuthHeader: string | null = null;
let observedOrganizationHeader: string | null = null;

const server = setupServer(
  http.get(`${apiBaseUrl}/pipeline/runs/:runId`, ({ request, params }) => {
    observedAuthHeader = request.headers.get("authorization");
    observedOrganizationHeader = request.headers.get("x-organization-id");
    return HttpResponse.json({
      pipeline_run_id: String(params.runId),
      pipeline_type: "chat.answer",
      status: "completed",
      nodes: [
        {
          id: "retrieve",
          label: "Retrieve",
          section: "query",
          status: "completed",
          duration_ms: 112,
        },
      ],
      edges: [],
    });
  }),
);

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  clearSessionStorage();
  observedAuthHeader = null;
  observedOrganizationHeader = null;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  writeSessionToStorage({
    userId: "user-1",
    email: "owner@example.com",
    role: "owner",
    organizationId: "c8ae2f17-c58e-499e-88bf-e6b0a8648c21",
    organizationName: "Org One",
    accessToken: "session-access-token",
  });
});

describe("RagPipelinePage auth integration (MSW)", () => {
  it("loads pipeline graph for authenticated session without manual token entry", async () => {
    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-auth-1");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    expect(await screen.findByText("Type: chat.answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrieve" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Bearer token (optional)")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Organization id (optional)")).not.toBeInTheDocument();
    expect(observedAuthHeader).toBe("Bearer session-access-token");
    expect(observedOrganizationHeader).toBe("c8ae2f17-c58e-499e-88bf-e6b0a8648c21");
  });

  it("renders shared forbidden state when API returns 403", async () => {
    server.use(
      http.get(`${apiBaseUrl}/pipeline/runs/:runId`, () =>
        HttpResponse.json(
          { detail: "forbidden internals", request_id: "pipeline-403-req" },
          { status: 403 },
        ),
      ),
    );

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-403");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    expect(await screen.findByRole("heading", { name: "Action blocked" })).toBeInTheDocument();
    expect(
      screen.getByText("You do not have permission to view this pipeline run. Check your role or organization scope."),
    ).toBeInTheDocument();
    expect(screen.queryByText("forbidden internals")).not.toBeInTheDocument();
  });

  it("handles 401 with shared session-invalid messaging", async () => {
    server.use(
      http.get(`${apiBaseUrl}/pipeline/runs/:runId`, () =>
        HttpResponse.json({ detail: "missing token" }, { status: 401 }),
      ),
    );

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-401");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    await waitFor(() => {
      expect(screen.getByText("Your session is not valid. Sign in again.")).toBeInTheDocument();
    });
  });
});
