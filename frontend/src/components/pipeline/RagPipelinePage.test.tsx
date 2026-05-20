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
  resolvePipelineRun,
  type PipelineRunGraphResponse,
} from "@/lib/pipeline";
import { normalizeApiError } from "@/lib/api/errors";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

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
    resolvePipelineRun: vi.fn(),
  };
});

const mockedFetchPipelineRunGraph = vi.mocked(fetchPipelineRunGraph);
const mockedFetchPipelineNodeDetail = vi.mocked(fetchPipelineNodeDetail);
const mockedResolvePipelineRun = vi.mocked(resolvePipelineRun);

describe("RagPipelinePage", () => {
  beforeEach(() => {
    mockNavigation.searchParams = new URLSearchParams();
    mockedFetchPipelineRunGraph.mockReset();
    mockedFetchPipelineNodeDetail.mockReset();
    mockedResolvePipelineRun.mockReset();
    mockedFetchPipelineRunGraph.mockResolvedValue(fallbackPipelineGraph);
    mockedFetchPipelineNodeDetail.mockResolvedValue(fallbackNodeDetail);
    mockedResolvePipelineRun.mockRejectedValue(
      normalizeApiError({
        status: 404,
        payload: { detail: "Pipeline run not found" },
      }),
    );
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

  it("shows run type filter labels for document, chat, and evaluation telemetry", () => {
    render(<RagPipelinePage />);

    expect(screen.getByRole("option", { name: "Document processing (document.process)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Chat answer (chat.answer)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Evaluation run (evaluation.run)" })).toBeInTheDocument();
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

  it("initializes from URL params and auto-loads a run graph", async () => {
    const loadedGraph: PipelineRunGraphResponse = {
      pipeline_run_id: "run-url-1",
      pipeline_type: "chat.answer",
      status: "completed",
      nodes: [
        {
          id: "retrieve",
          label: "Retrieve",
          section: "query",
          status: "completed",
          duration_ms: 64,
        },
      ],
      edges: [],
    };

    mockNavigation.searchParams = new URLSearchParams({
      run_id: "run-url-1",
      run_type: "chat.answer",
      document_id: "doc-url-1",
    });
    mockedFetchPipelineRunGraph.mockResolvedValueOnce(loadedGraph);

    render(<RagPipelinePage />);

    await waitFor(() => {
      expect(mockedFetchPipelineRunGraph).toHaveBeenCalledWith("run-url-1");
    });
    expect(screen.getByPlaceholderText("Pipeline run id")).toHaveValue("run-url-1");
    expect(screen.getByRole("combobox")).toHaveValue("chat.answer");
    expect(screen.getByText("Document: doc-url-1")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Retrieve" })).toBeInTheDocument();
  });

  it("shows safe deep-link empty state when run id is missing", async () => {
    mockNavigation.searchParams = new URLSearchParams({
      document_id: "doc-missing-run",
    });

    render(<RagPipelinePage />);

    await waitFor(() => {
      expect(
        screen.getByText("No pipeline run was found yet for this resource. Retry after processing completes."),
      ).toBeInTheDocument();
    });
    expect(mockedResolvePipelineRun).toHaveBeenCalledWith({
      run_type: null,
      document_id: "doc-missing-run",
      chat_message_id: null,
      evaluation_run_id: null,
    });
    expect(screen.getByText("Document: doc-missing-run")).toBeInTheDocument();
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

  it("renders chat telemetry fixture nodes when chat run type filter is selected", async () => {
    render(<RagPipelinePage />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "chat.answer");

    expect(screen.getByRole("button", { name: "Embed query" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrieve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build prompt" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate citations" })).toBeInTheDocument();
    expect(screen.getByText("Type: chat.answer")).toBeInTheDocument();
  });

  it("renders evaluation telemetry fixture nodes when evaluation run type filter is selected", async () => {
    render(<RagPipelinePage />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "evaluation.run");

    expect(screen.getByRole("button", { name: "Load set" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run question" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Score metrics" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aggregate summary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Persist results" })).toBeInTheDocument();
    expect(screen.getByText("Type: evaluation.run")).toBeInTheDocument();
  });

  it("falls back safely for unknown node payloads and partial telemetry", async () => {
    mockedFetchPipelineRunGraph.mockResolvedValueOnce({
      pipeline_run_id: "",
      pipeline_type: "chat.answer",
      status: "",
      nodes: [
        {
          id: "unknown-step",
          section: "future",
          status: "unexpected",
        },
      ],
      edges: [{ id: "e-unknown", source: "missing-source", target: "unknown-step" }],
    } as unknown as PipelineRunGraphResponse);

    render(<RagPipelinePage />);

    await userEvent.type(screen.getByPlaceholderText("Pipeline run id"), "run-malformed");
    await userEvent.click(screen.getByRole("button", { name: "Load Run" }));

    expect(await screen.findByRole("button", { name: "unknown step" })).toBeInTheDocument();
    expect(screen.getByText("Type: chat.answer")).toBeInTheDocument();
    expect(screen.queryByText("Current run type (chat.answer) is filtered out. Update the run type filter to view this graph.")).not.toBeInTheDocument();
  });

  it("applies run type filter and shows mismatch state", async () => {
    render(<RagPipelinePage />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "chat.answer");
    await userEvent.selectOptions(screen.getByRole("combobox"), "all");
    await userEvent.selectOptions(screen.getByRole("combobox"), "document.process");

    expect(screen.getByText("Type: document.process")).toBeInTheDocument();
  });
});
