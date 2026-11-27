"use client";

import { useMemo } from "react";

import { useTranslations } from "next-intl";
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
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import type {
  FlowNode,
  FlowNodeData,
} from "@/components/pipeline/RagPipelinePage";
import type {
  PipelineNode,
  PipelineNodeStatus,
  PipelineRunGraphResponse,
} from "@/lib/pipeline";

type StatusMeta = {
  badgeClass: string;
  nodeClass: string;
};

const statusMeta: Record<PipelineNodeStatus, StatusMeta> = {
  completed: {
    badgeClass: "bg-emerald-100 text-emerald-800",
    nodeClass: "border-emerald-300 bg-white",
  },
  running: {
    badgeClass: "bg-blue-100 text-blue-800",
    nodeClass: "border-[#3a57d4] bg-white shadow-md",
  },
  failed: {
    badgeClass: "bg-rose-100 text-rose-800",
    nodeClass: "border-rose-400 bg-rose-50",
  },
  skipped: {
    badgeClass: "bg-amber-100 text-amber-800",
    nodeClass: "border-amber-300 bg-amber-50",
  },
  pending: {
    badgeClass: "bg-[#eceaf7] text-[#69657f]",
    nodeClass: "border-[#d4d0e8] bg-white/90",
  },
};

const nodeTypes = {
  pipelineNode: PipelineFlowNode,
} satisfies NodeTypes;

function buildFlowEdges(
  edges: PipelineRunGraphResponse["edges"],
  nodes: PipelineNode[],
): Edge[] {
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
  const t = useTranslations("pipeline");
  const meta = statusMeta[data.status];

  return (
    <div
      className={`relative w-[250px] rounded-xl border p-3 transition ${meta.nodeClass} ${
        selected ? "ring-2 ring-[#3525cd]/40" : ""
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-0 !bg-[#8f88c7]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-0 !bg-[#8f88c7]"
      />

      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-base font-bold text-[#222033]">{data.label}</p>
          <p className="text-[11px] font-bold tracking-wide text-[#7a768f] uppercase">
            {t(`sections.${data.section}`)}
          </p>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${meta.badgeClass}`}
        >
          {t(`statuses.${data.status}`)}
        </span>
      </div>

      <p className="mb-2 text-xs text-[#5f5b72]">{data.description}</p>
      <p
        className="text-[11px] text-[#5f5b72]"
        style={{
          fontFamily:
            "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {data.duration}
      </p>
    </div>
  );
}

/** React Flow canvas of the pipeline explorer (loaded on demand, R07-03). */
export function PipelineFlowCanvas({
  nodes,
  graphNodes,
  graphEdges,
  onNodeSelect,
}: {
  nodes: FlowNode[];
  graphNodes: PipelineNode[];
  graphEdges: PipelineRunGraphResponse["edges"];
  onNodeSelect: (nodeId: string) => void;
}) {
  const edges = useMemo(
    () => buildFlowEdges(graphEdges, graphNodes),
    [graphEdges, graphNodes],
  );
  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.5}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={(_, flowNode) => onNodeSelect(flowNode.id)}
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
  );
}
