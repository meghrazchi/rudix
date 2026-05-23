from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.pipeline import PipelineEvent

_NODE_LABELS: dict[str, str] = {
    "resolve_document": "Resolve document",
    "extract": "Extract",
    "clean": "Clean",
    "index_cleanup": "Index cleanup",
    "chunk": "Chunk",
    "embed": "Embed",
    "index": "Index",
    "retrieve": "Retrieve",
    "rerank": "Rerank",
    "build_prompt": "Build prompt",
    "llm": "LLM",
    "validate_citations": "Validate citations",
    "persist_response": "Persist response",
    "delete_index": "Delete index",
    "delete_storage": "Delete storage",
    "delete_metadata": "Delete metadata",
    "load_set": "Load set",
    "run_question": "Run question",
    "score_metrics": "Score metrics",
    "aggregate_summary": "Aggregate summary",
    "persist_results": "Persist results",
}

_NODE_DESCRIPTIONS: dict[str, str] = {
    "resolve_document": "Load and validate document context for the run.",
    "extract": "Extract raw text and metadata from source files.",
    "clean": "Normalize extracted text before chunking.",
    "index_cleanup": "Remove stale vectors for re-index operations.",
    "chunk": "Split text into retrieval-sized chunks.",
    "embed": "Generate vector embeddings for chunks.",
    "index": "Upsert embedded chunks into vector storage.",
    "retrieve": "Fetch context candidates for the query.",
    "rerank": "Re-rank retrieval results before prompting.",
    "build_prompt": "Compose grounded prompt with selected context.",
    "llm": "Generate answer from grounded prompt.",
    "validate_citations": "Validate citation consistency and grounding.",
    "persist_response": "Persist response payload and metadata.",
    "delete_index": "Delete document vectors from index storage.",
    "delete_storage": "Delete source object from storage.",
    "delete_metadata": "Delete metadata records from relational storage.",
    "load_set": "Load evaluation set and configuration.",
    "run_question": "Execute evaluation question workload.",
    "score_metrics": "Compute retrieval and answer quality metrics.",
    "aggregate_summary": "Aggregate run-level summary metrics.",
    "persist_results": "Persist evaluation results and summaries.",
}


def canonical_pipeline_type(pipeline_type: str) -> str:
    if pipeline_type in {"document.process", "document.reindex", "document.delete"}:
        return "document.process"
    if pipeline_type == "chat.query":
        return "chat.answer"
    if pipeline_type == "evaluation.run":
        return "evaluation.run"
    return pipeline_type


def pipeline_section_for_type(pipeline_type: str) -> str:
    canonical_type = canonical_pipeline_type(pipeline_type)
    if canonical_type == "document.process":
        return "ingestion"
    if canonical_type == "evaluation.run":
        return "evaluation"
    return "query"


def pipeline_node_label(node_name: str) -> str:
    if node_name in _NODE_LABELS:
        return _NODE_LABELS[node_name]
    normalized = node_name.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return normalized.title() if normalized else "Node"


def pipeline_node_description(node_name: str) -> str:
    return _NODE_DESCRIPTIONS.get(
        node_name,
        "Node-specific execution data and metrics are shown here when run events are available.",
    )


def pipeline_event_status_to_node_status(event_status: str) -> str:
    if event_status == "started":
        return "running"
    if event_status in {"completed", "failed", "skipped"}:
        return event_status
    return "pending"


def _as_object(value: Any) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_log_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(line) for line in value]


def _node_metrics(event: PipelineEvent) -> dict[str, object]:
    outputs = _as_object(event.outputs_json)
    metrics = outputs.get("metrics")
    if isinstance(metrics, dict):
        return {str(key): item for key, item in metrics.items()}
    return {}


@dataclass(slots=True)
class AggregatedPipelineNode:
    node_id: str
    label: str
    description: str
    section: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    metrics: dict[str, object]


def aggregate_pipeline_nodes(
    *, pipeline_type: str, events: list[PipelineEvent]
) -> list[AggregatedPipelineNode]:
    by_node_name: dict[str, list[PipelineEvent]] = {}
    first_sequence: dict[str, int] = {}

    for event in events:
        node_name = event.node_name
        by_node_name.setdefault(node_name, []).append(event)
        if node_name not in first_sequence:
            first_sequence[node_name] = event.sequence

    section = pipeline_section_for_type(pipeline_type)
    ordered_node_names = sorted(
        first_sequence.keys(), key=lambda node_name: first_sequence[node_name]
    )

    nodes: list[AggregatedPipelineNode] = []
    for node_name in ordered_node_names:
        node_events = by_node_name[node_name]
        latest_event = node_events[-1]
        started_candidates = [
            item.started_at for item in node_events if item.started_at is not None
        ]
        completed_candidates = [
            item.completed_at for item in node_events if item.completed_at is not None
        ]

        started_at = min(started_candidates) if started_candidates else latest_event.started_at
        completed_at = (
            max(completed_candidates) if completed_candidates else latest_event.completed_at
        )
        duration_ms = latest_event.duration_ms
        if duration_ms is None and started_at is not None and completed_at is not None:
            duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)

        nodes.append(
            AggregatedPipelineNode(
                node_id=node_name,
                label=pipeline_node_label(node_name),
                description=pipeline_node_description(node_name),
                section=section,
                status=pipeline_event_status_to_node_status(latest_event.status),
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                metrics=_node_metrics(latest_event),
            )
        )

    return nodes


def build_pipeline_edges(node_ids_in_order: list[str]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for index in range(len(node_ids_in_order) - 1):
        source = node_ids_in_order[index]
        target = node_ids_in_order[index + 1]
        edges.append(
            {
                "id": f"{source}->{target}:{index}",
                "source": source,
                "target": target,
            }
        )
    return edges


def build_pipeline_node_detail(*, events: list[PipelineEvent]) -> dict[str, object]:
    latest_event = events[-1]

    started_at = latest_event.started_at
    completed_at = latest_event.completed_at
    duration_ms = latest_event.duration_ms
    if duration_ms is None and started_at is not None and completed_at is not None:
        duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)

    inputs_payload: dict[str, object] = {}
    for candidate in events:
        candidate_inputs = _as_object(candidate.inputs_json)
        if candidate_inputs:
            inputs_payload = candidate_inputs
            break

    outputs_payload = _as_object(latest_event.outputs_json)
    config_payload = _as_object(latest_event.config_json)
    logs_payload = _as_log_lines(latest_event.logs_json)
    error_details_payload = _as_object(latest_event.error_details_json)

    return {
        "node_id": latest_event.node_name,
        "title": pipeline_node_label(latest_event.node_name),
        "description": pipeline_node_description(latest_event.node_name),
        "status": pipeline_event_status_to_node_status(latest_event.status),
        "inputs": inputs_payload,
        "outputs": outputs_payload,
        "config": config_payload,
        "logs": logs_payload,
        "error_message": latest_event.error_message,
        "error_details": error_details_payload,
        "metrics": _node_metrics(latest_event),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
    }
