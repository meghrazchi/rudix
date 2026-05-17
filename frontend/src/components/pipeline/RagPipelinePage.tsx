"use client";

import { useMemo, useState } from "react";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  fallbackNodeDetail,
  fallbackPipelineGraph,
  fetchPipelineNodeDetail,
  fetchPipelineRunGraph,
  type PipelineNode,
  type PipelineNodeDetailResponse,
  type PipelineNodeStatus,
  type PipelineRunGraphResponse,
} from "@/lib/pipeline";

type RunTypeFilter = "all" | "document.process" | "chat.answer" | "evaluation.run";

type StatusMeta = {
  label: string;
  badgeClass: string;
  nodeClass: string;
};

type FlowNodeData = {
  label: string;
  description: string;
  duration: string;
  status: PipelineNodeStatus;
  section: PipelineNode["section"];
};

type FlowNode = Node<FlowNodeData, "pipelineNode">;

const statusMeta: Record<PipelineNodeStatus, StatusMeta> = {
  completed: {
    label: "SUCCESS",
    badgeClass: "bg-emerald-100 text-emerald-800",
    nodeClass: "border-emerald-300 bg-white",
  },
  running: {
    label: "PROCESSING",
    badgeClass: "bg-blue-100 text-blue-800",
    nodeClass: "border-[#3a57d4] bg-white shadow-md",
  },
  failed: {
    label: "FAILED",
    badgeClass: "bg-rose-100 text-rose-800",
    nodeClass: "border-rose-400 bg-rose-50",
  },
  skipped: {
    label: "SKIPPED",
    badgeClass: "bg-amber-100 text-amber-800",
    nodeClass: "border-amber-300 bg-amber-50",
  },
  pending: {
    label: "QUEUED",
    badgeClass: "bg-[#eceaf7] text-[#69657f]",
    nodeClass: "border-[#d4d0e8] bg-white/90",
  },
};

const sectionX: Record<PipelineNode["section"], number> = {
  ingestion: 40,
  query: 420,
  evaluation: 800,
};

const sectionLabel: Record<PipelineNode["section"], string> = {
  ingestion: "Ingestion",
  query: "Query",
  evaluation: "Evaluation",
};

const nodeTypes = {
  pipelineNode: PipelineFlowNode,
} satisfies NodeTypes;

function stringifyValue(value: unknown): string {
  if (value == null) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function formatDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) {
    return "-";
  }
  return `${durationMs.toLocaleString()} ms`;
}

function deriveNodeDetail(node: PipelineNode): PipelineNodeDetailResponse {
  return {
    ...fallbackNodeDetail,
    node_id: node.id,
    title: node.label,
    description:
      node.description ??
      "Node-specific execution data and metrics are shown here when run events are available.",
    status: node.status,
    metrics: {
      ...(node.metrics ?? {}),
      duration_ms: node.duration_ms ?? null,
    },
    duration_ms: node.duration_ms ?? null,
    started_at: node.started_at ?? null,
    completed_at: node.completed_at ?? null,
  };
}

function matchesDocumentFilter(node: PipelineNode, filter: string): boolean {
  const normalized = filter.trim().toLowerCase();
  if (!normalized) {
    return true;
  }

  const searchable = [node.id, node.label, node.description ?? "", JSON.stringify(node.metrics ?? {})]
    .join(" ")
    .toLowerCase();

  return searchable.includes(normalized);
}

function buildFlowNodes(nodes: PipelineNode[], selectedNodeId: string): FlowNode[] {
  const grouped = {
    ingestion: [] as PipelineNode[],
    query: [] as PipelineNode[],
    evaluation: [] as PipelineNode[],
  };

  for (const node of nodes) {
    grouped[node.section].push(node);
  }

  return (Object.keys(grouped) as PipelineNode["section"][]).flatMap((section) =>
    grouped[section].map((node, index) => ({
      id: node.id,
      type: "pipelineNode",
      position: {
        x: sectionX[section],
        y: 56 + index * 158,
      },
      selected: node.id === selectedNodeId,
      data: {
        label: node.label,
        description: node.description ?? "Execution node",
        duration: formatDuration(node.duration_ms),
        status: node.status,
        section,
      },
    })),
  );
}

function buildFlowEdges(edges: PipelineRunGraphResponse["edges"], nodes: PipelineNode[]): Edge[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return edges.map((edge) => {
    const sourceStatus = byId.get(edge.source)?.status;
    const isQueued = sourceStatus === "pending";
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: sourceStatus === "running",
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isQueued ? "#bcb8d2" : "#7f79b6",
      },
      style: {
        strokeWidth: 2,
        stroke: isQueued ? "#bcb8d2" : "#7f79b6",
        strokeDasharray: isQueued ? "4 4" : undefined,
      },
    };
  });
}

function PipelineFlowNode({ data, selected }: NodeProps<FlowNode>) {
  const meta = statusMeta[data.status];

  return (
    <div
      className={`relative w-[250px] rounded-xl border p-3 transition ${meta.nodeClass} ${
        selected ? "ring-2 ring-[#3525cd]/40" : ""
      }`}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-[#8f88c7]" />
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-[#8f88c7]" />

      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-base font-bold text-[#222033]">{data.label}</p>
          <p className="text-[11px] font-bold uppercase tracking-wide text-[#7a768f]">{sectionLabel[data.section]}</p>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${meta.badgeClass}`}>{meta.label}</span>
      </div>

      <p className="mb-2 text-xs text-[#5f5b72]">{data.description}</p>
      <p
        className="text-[11px] text-[#5f5b72]"
        style={{ fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace" }}
      >
        {data.duration}
      </p>
    </div>
  );
}

export function RagPipelinePage() {
  const [runId, setRunId] = useState("");
  const [runTypeFilter, setRunTypeFilter] = useState<RunTypeFilter>("all");
  const [documentFilter, setDocumentFilter] = useState("");

  const [graph, setGraph] = useState<PipelineRunGraphResponse>(fallbackPipelineGraph);
  const [selectedNodeId, setSelectedNodeId] = useState<string>(fallbackPipelineGraph.nodes[0]?.id ?? "");
  const [nodeDetail, setNodeDetail] = useState<PipelineNodeDetailResponse>(fallbackNodeDetail);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [loadingNode, setLoadingNode] = useState(false);
  const [errorText, setErrorText] = useState<string | null>("Showing sample graph. Enter a run id to load backend data.");
  const [forbiddenState, setForbiddenState] = useState<{
    description: string;
    requestId: string | null;
  } | null>(null);

  const nodeLookup = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const runTypeMismatch = runTypeFilter !== "all" && graph.pipeline_type !== runTypeFilter;
  const filteredNodes = useMemo(
    () => (runTypeMismatch ? [] : graph.nodes.filter((node) => matchesDocumentFilter(node, documentFilter))),
    [graph.nodes, documentFilter, runTypeMismatch],
  );
  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map((node) => node.id)), [filteredNodes]);
  const filteredEdges = useMemo(
    () => graph.edges.filter((edge) => filteredNodeIds.has(edge.source) && filteredNodeIds.has(edge.target)),
    [graph.edges, filteredNodeIds],
  );
  const effectiveSelectedNodeId = useMemo(() => {
    if (filteredNodes.some((node) => node.id === selectedNodeId)) {
      return selectedNodeId;
    }
    return filteredNodes[0]?.id ?? "";
  }, [filteredNodes, selectedNodeId]);
  const displayedNodeDetail = useMemo(() => {
    const selectedNode = filteredNodes.find((node) => node.id === effectiveSelectedNodeId);
    if (!selectedNode) {
      return nodeDetail;
    }
    if (selectedNode.id !== nodeDetail.node_id) {
      return deriveNodeDetail(selectedNode);
    }
    return nodeDetail;
  }, [effectiveSelectedNodeId, filteredNodes, nodeDetail]);

  const flowNodes = useMemo(() => buildFlowNodes(filteredNodes, effectiveSelectedNodeId), [effectiveSelectedNodeId, filteredNodes]);
  const flowEdges = useMemo(() => buildFlowEdges(filteredEdges, filteredNodes), [filteredEdges, filteredNodes]);

  const runLabel = runId.trim() ? runId.trim() : graph.pipeline_run_id;

  async function loadGraph() {
    if (!runId.trim()) {
      setGraph(fallbackPipelineGraph);
      const firstNode = fallbackPipelineGraph.nodes[0];
      if (firstNode) {
        setSelectedNodeId(firstNode.id);
        setNodeDetail(deriveNodeDetail(firstNode));
      }
      setForbiddenState(null);
      setErrorText("Showing sample graph. Enter a run id to load backend data.");
      return;
    }

    setLoadingGraph(true);
    setForbiddenState(null);
    setErrorText(null);
    try {
      const loaded = await fetchPipelineRunGraph(runId.trim());
      setGraph(loaded);
      const firstNode = loaded.nodes[0];
      if (firstNode) {
        setSelectedNodeId(firstNode.id);
        setNodeDetail(deriveNodeDetail(firstNode));
      }
    } catch (error) {
      setGraph(fallbackPipelineGraph);
      const firstNode = fallbackPipelineGraph.nodes[0];
      if (firstNode) {
        setSelectedNodeId(firstNode.id);
        setNodeDetail(deriveNodeDetail(firstNode));
      }

      if (isForbiddenError(error)) {
        setForbiddenState({
          description:
            "You do not have permission to view this pipeline run. Check your role or organization scope.",
          requestId: extractRequestIdFromError(error),
        });
      } else if (isApiClientError(error) && error.status === 401) {
        setErrorText(getApiErrorMessage(error));
      } else {
        setErrorText("Could not load backend run graph. Fallback sample data is displayed.");
      }
    } finally {
      setLoadingGraph(false);
    }
  }

  async function selectNode(node: PipelineNode) {
    setSelectedNodeId(node.id);
    setNodeDetail(deriveNodeDetail(node));

    if (!runId.trim()) {
      return;
    }

    setLoadingNode(true);
    try {
      const detail = await fetchPipelineNodeDetail(runId.trim(), node.id);
      setNodeDetail(detail);
      setForbiddenState(null);
      setErrorText(null);
    } catch (error) {
      setNodeDetail(deriveNodeDetail(node));
      if (isForbiddenError(error)) {
        setForbiddenState({
          description: "You do not have permission to inspect this node detail.",
          requestId: extractRequestIdFromError(error),
        });
      } else if (isApiClientError(error) && error.status === 401) {
        setErrorText(getApiErrorMessage(error));
      } else {
        setErrorText("Node detail endpoint not available for this run. Showing best-effort preview.");
      }
    } finally {
      setLoadingNode(false);
    }
  }

  function refreshGraph() {
    void loadGraph();
  }

  return (
    <div className="flex h-[calc(100vh-85px)] min-h-[700px] flex-col lg:flex-row">
      <section className="relative flex-1 overflow-hidden border-b border-[#d8d5e8] bg-white lg:border-b-0 lg:border-r">
        <div
          className="absolute inset-0 opacity-25"
          style={{
            backgroundImage: "radial-gradient(circle, #cbc8dd 1px, transparent 1px)",
            backgroundSize: "26px 26px",
          }}
        />

        <div className="relative z-10 flex h-full flex-col">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void loadGraph();
            }}
            className="flex flex-wrap items-center gap-2 border-b border-[#dad7ea] bg-white/95 px-4 py-3 lg:flex-nowrap"
          >
            <input
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              placeholder="Pipeline run id"
              className="h-10 min-w-[180px] flex-1 rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            />
            <select
              value={runTypeFilter}
              onChange={(event) => setRunTypeFilter(event.target.value as RunTypeFilter)}
              className="h-10 min-w-[142px] rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            >
              <option value="all">All run types</option>
              <option value="document.process">document.process</option>
              <option value="chat.answer">chat.answer</option>
              <option value="evaluation.run">evaluation.run</option>
            </select>
            <input
              value={documentFilter}
              onChange={(event) => setDocumentFilter(event.target.value)}
              placeholder="Document filter"
              className="h-10 min-w-[150px] flex-1 rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
            />
            <div className="ml-auto flex shrink-0 gap-2">
              <button
                type="submit"
                disabled={loadingGraph}
                className="h-10 whitespace-nowrap rounded-lg bg-[#3525cd] px-5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-60"
              >
                {loadingGraph ? "Loading..." : "Load Run"}
              </button>
              <button
                type="button"
                onClick={refreshGraph}
                disabled={loadingGraph}
                className="h-10 whitespace-nowrap rounded-lg border border-[#d2cee6] bg-white px-4 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff] disabled:opacity-60"
              >
                Refresh
              </button>
            </div>
          </form>

          <div className="flex flex-wrap items-center gap-3 border-b border-[#e8e4f5] bg-[#f8f6ff] px-4 py-2 text-xs font-semibold uppercase tracking-wide text-[#5f5b72]">
            <span>Run: {runLabel}</span>
            <span>Type: {graph.pipeline_type}</span>
            <span>Status: {graph.status}</span>
          </div>

          {forbiddenState ? (
            <div className="border-b border-[#e8e4f5] bg-[#f5f3ff] p-3">
              <ForbiddenState
                compact
                title="Action blocked"
                description={forbiddenState.description}
                requestId={forbiddenState.requestId}
              />
            </div>
          ) : null}

          {errorText ? (
            <div className="border-b border-[#e8e4f5] bg-[#f2efff] px-4 py-2 text-sm text-[#4f46a7]">{errorText}</div>
          ) : null}

          <div className="relative min-h-0 flex-1">
            {runTypeMismatch ? (
              <div className="flex h-full items-center justify-center px-6 text-sm text-[#67637c]">
                Current run type ({graph.pipeline_type}) is filtered out. Update the run type filter to view this graph.
              </div>
            ) : flowNodes.length === 0 ? (
              <div className="flex h-full items-center justify-center px-6 text-sm text-[#67637c]">
                No nodes match the current document filter.
              </div>
            ) : (
              <ReactFlowProvider>
                <ReactFlow
                  nodes={flowNodes}
                  edges={flowEdges}
                  nodeTypes={nodeTypes}
                  fitView
                  fitViewOptions={{ padding: 0.2 }}
                  minZoom={0.5}
                  maxZoom={1.6}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable
                  onNodeClick={(_, flowNode) => {
                    const original = nodeLookup.get(flowNode.id);
                    if (original) {
                      void selectNode(original);
                    }
                  }}
                  className="h-full w-full bg-transparent"
                  proOptions={{ hideAttribution: true }}
                >
                  <Background color="#dfdbee" gap={24} size={1} />
                  <MiniMap
                    pannable
                    zoomable
                    nodeColor={(flowNode) => {
                      const status = (flowNode.data as FlowNodeData).status;
                      if (status === "completed") {
                        return "#10b981";
                      }
                      if (status === "running") {
                        return "#3b82f6";
                      }
                      if (status === "failed") {
                        return "#f43f5e";
                      }
                      if (status === "skipped") {
                        return "#f59e0b";
                      }
                      return "#9ca3af";
                    }}
                  />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </ReactFlowProvider>
            )}
          </div>
        </div>
      </section>

      <aside className="w-full max-w-full border-t border-[#d8d5e8] bg-white lg:w-[420px] lg:border-t-0">
        <div className="border-b border-[#d8d5e8] px-5 py-4">
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-[#3525cd]">Node Selected</div>
          <h3 className="text-xl font-bold text-[#2d2a3f]">{displayedNodeDetail.title}</h3>
          <p className="mt-1 text-sm text-[#626074]">{displayedNodeDetail.description}</p>
        </div>

        <div className="max-h-[calc(100vh-280px)] space-y-5 overflow-auto px-5 py-5">
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="Status" value={statusMeta[displayedNodeDetail.status].label} />
              <MetricCard label="Duration" value={formatDuration(displayedNodeDetail.duration_ms)} />
              <MetricCard label="Started" value={displayedNodeDetail.started_at ?? "-"} mono />
              <MetricCard label="Completed" value={displayedNodeDetail.completed_at ?? "-"} mono />
            </div>

            <KeyValueSection title="Inputs" values={displayedNodeDetail.inputs} />
            <KeyValueSection title="Outputs" values={displayedNodeDetail.outputs} />
            <KeyValueSection title="Config" values={displayedNodeDetail.config} />
            <KeyValueSection title="Metrics" values={displayedNodeDetail.metrics} />

            <section>
              <h4 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#66637a]">Logs</h4>
              <div
                className="space-y-1 rounded-xl bg-[#2f2b3f] p-3 text-xs text-[#efeefe]"
                style={{ fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace" }}
              >
                {loadingNode ? <p>Loading node detail...</p> : null}
                {displayedNodeDetail.logs.length === 0 && !loadingNode ? <p>No logs available.</p> : null}
                {displayedNodeDetail.logs.map((line) => (
                  <p key={line}>- {line}</p>
                ))}
              </div>
            </section>

            {displayedNodeDetail.error_message ? (
              <section className="rounded-xl border border-rose-200 bg-rose-50 p-3">
                <h4 className="mb-1 text-xs font-bold uppercase tracking-wide text-rose-700">Error</h4>
                <p className="text-sm text-rose-800">{displayedNodeDetail.error_message}</p>
              </section>
            ) : null}
          </div>
      </aside>
    </div>
  );
}

type MetricCardProps = {
  label: string;
  value: string;
  mono?: boolean;
};

function MetricCard({ label, value, mono = false }: MetricCardProps) {
  return (
    <div className="rounded-xl border border-[#e0dced] bg-[#f8f6ff] p-3">
      <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-[#6a667f]">{label}</p>
      <p
        className={`text-sm font-semibold text-[#27233a] ${mono ? "break-all" : ""}`}
        style={{ fontFamily: mono ? "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace" : undefined }}
      >
        {value}
      </p>
    </div>
  );
}

type KeyValueSectionProps = {
  title: string;
  values: Record<string, unknown>;
};

function KeyValueSection({ title, values }: KeyValueSectionProps) {
  const entries = Object.entries(values);
  return (
    <section>
      <h4 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#66637a]">{title}</h4>
      <div className="overflow-hidden rounded-xl border border-[#dcd7ea] bg-white">
        {entries.length === 0 ? (
          <div className="px-3 py-2 text-sm text-[#777489]">No data.</div>
        ) : (
          entries.map(([key, value]) => (
            <div key={key} className="grid grid-cols-2 gap-2 border-b border-[#ece8f6] px-3 py-2 last:border-b-0">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#7b7890]">{key}</span>
              <span
                className="text-xs text-[#2d2940]"
                style={{ fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace" }}
              >
                {stringifyValue(value)}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
