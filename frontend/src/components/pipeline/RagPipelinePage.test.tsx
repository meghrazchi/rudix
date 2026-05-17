import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RagPipelinePage } from "@/components/pipeline/RagPipelinePage";
import {
  fallbackNodeDetail,
  fallbackPipelineGraph,
  fetchPipelineNodeDetail,
  fetchPipelineRunGraph,
  type PipelineRunGraphResponse,
} from "@/lib/pipeline";
import { normalizeApiError } from "@/lib/api/errors";

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

vi.mock("@/lib/pipeline", async () => {
  const actual = await vi.importActual<typeof import("@/lib/pipeline")>("@/lib/pipeline");
  return {
    ...actual,
    fetchPipelineRunGraph: vi.fn(),
    fetchPipelineNodeDetail: vi.fn(),
  };
});

const mockedFetchPipelineRunGraph = vi.mocked(fetchPipelineRunGraph);
const mockedFetchPipelineNodeDetail = vi.mocked(fetchPipelineNodeDetail);

describe("RagPipelinePage", () => {
  beforeEach(() => {
    mockedFetchPipelineRunGraph.mockReset();
    mockedFetchPipelineNodeDetail.mockReset();
    mockedFetchPipelineRunGraph.mockResolvedValue(fallbackPipelineGraph);
    mockedFetchPipelineNodeDetail.mockResolvedValue(fallbackNodeDetail);
  });

  it("renders fallback graph and updates side panel when a node is clicked", async () => {
    render(<RagPipelinePage />);

    expect(screen.getByText("Showing sample graph. Enter a run id to load backend data.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Chunk" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chunk" })).toBeInTheDocument();
    });
  });

  it("loads run graph from API and renders loaded nodes", async () => {
    const loadedGraph: PipelineRunGraphResponse = {
      pipeline_run_id: "run-abc",
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
    };

    mockedFetchPipelineRunGraph.mockResolvedValueOnce(loadedGraph);

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-abc");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    await waitFor(() => {
      expect(mockedFetchPipelineRunGraph).toHaveBeenCalledWith("run-abc");
    });
    expect(screen.getByText("Type: chat.answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrieve" })).toBeInTheDocument();
  });

  it("shows permission-aware error on forbidden run access", async () => {
    mockedFetchPipelineRunGraph.mockRejectedValueOnce(
      normalizeApiError({
        status: 403,
        payload: { detail: "forbidden internal detail" },
        requestId: "forbidden-req-id",
      }),
    );

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-forbidden");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    await waitFor(() => {
      expect(
        screen.getByText(
          "You do not have permission to view this pipeline run. Check your role or organization scope.",
        ),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Action blocked" })).toBeInTheDocument();
  });

  it("shows shared unauthorized message when API returns 401", async () => {
    mockedFetchPipelineRunGraph.mockRejectedValueOnce(
      normalizeApiError({
        status: 401,
        payload: { detail: "missing token" },
      }),
    );

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-unauthorized");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    await waitFor(() => {
      expect(screen.getByText("Your session is not valid. Sign in again.")).toBeInTheDocument();
    });
  });

  it("applies run type filter and shows mismatch state", async () => {
    render(<RagPipelinePage />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "chat.answer");

    expect(screen.getByText("Current run type (document.process) is filtered out. Update the run type filter to view this graph.")).toBeInTheDocument();
  });
});
