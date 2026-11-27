"""Query intent, complexity, and retrieval scope interpretation for chat answers (R05-01)."""

from uuid import UUID

from app.domains.chat.schemas.chat import (
    ChatQueryRequest,
)
from app.domains.chat.schemas.trust_metadata import (
    QueryInterpretationRecord,
)
from app.domains.chat.services.answer_mode_service import (
    AnswerModeResult,
)
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
)
from app.domains.chat.services.query_rewriting_service import (
    QueryRewritingResult,
)
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
)

_QUERY_INTENT_LABELS: dict[str, str] = {
    "lookup": "Lookup",
    "summary": "Summary",
    "comparison": "Comparison",
    "policy": "Policy",
    "troubleshooting": "Troubleshooting",
    "compliance": "Compliance",
    "connector_search": "Connector search",
    "graph_entity_search": "Graph/entity search",
    "product_guidance": "Product guidance",
}


def _infer_query_intent(question: str) -> str:
    normalized = question.lower()
    if any(
        token in normalized
        for token in (
            "connector",
            "connectors",
            "integration",
            "integrations",
            "datasource",
            "data source",
            "slack",
            "jira",
            "salesforce",
            "sharepoint",
            "confluence",
            "google drive",
            "onedrive",
            "box",
        )
    ):
        return "connector_search"
    if any(
        token in normalized
        for token in (
            "graph",
            "entity",
            "entities",
            "relationship",
            "relationships",
            "linked to",
            "connected to",
            "reports to",
            "reporting line",
            "org chart",
        )
    ):
        return "graph_entity_search"
    if any(
        token in normalized
        for token in (
            "compare",
            "comparison",
            "difference",
            "differences",
            "versus",
            "vs ",
            " vs",
            "better than",
            "tradeoff",
            "trade-offs",
            "which is more",
        )
    ):
        return "comparison"
    if any(
        token in normalized
        for token in (
            "troubleshoot",
            "troubleshooting",
            "debug",
            "fix",
            "issue",
            "problem",
            "error",
            "failed",
            "not working",
            "why can't",
            "why is",
        )
    ):
        return "troubleshooting"
    if any(
        token in normalized
        for token in (
            "compliance",
            "compliant",
            "gdpr",
            "hipaa",
            "sox",
            "pci",
            "audit",
            "regulation",
            "regulatory",
            "retention",
            "privacy",
            "legal",
        )
    ):
        return "compliance"
    if any(
        token in normalized
        for token in (
            "summarize",
            "summarise",
            "summary",
            "overview",
            "brief",
            "recap",
            "what does",
            "tell me about",
        )
    ):
        return "summary"
    if any(
        token in normalized
        for token in (
            "policy",
            "policies",
            "guideline",
            "guidelines",
            "procedure",
            "procedures",
            "rule",
            "rules",
            "benefit",
            "benefits",
            "leave",
            "vacation",
            "expense",
            "expenses",
        )
    ):
        return "policy"
    return "lookup"


def _guidance_label(topic: str | None) -> str:
    if topic == "onboarding":
        return "Onboarding"
    if topic == "ui_help":
        return "UI help"
    if topic == "empty_state":
        return "Empty state help"
    if topic == "source_scope":
        return "Source scope guidance"
    if topic == "how_to_use":
        return "How to use Rudix"
    return "Product guidance"


def _query_complexity(
    *,
    intent: str,
    query_rewrite_result: QueryRewritingResult | None,
    question: str,
) -> str:
    if query_rewrite_result is not None and query_rewrite_result.decomposition_applied:
        return "multi_part"
    if query_rewrite_result is not None and query_rewrite_result.rewriting_applied:
        return "complex"
    if intent in {
        "comparison",
        "policy",
        "troubleshooting",
        "compliance",
        "connector_search",
        "graph_entity_search",
    }:
        return "complex"
    if len(question.split()) >= 18:
        return "complex"
    return "simple"


def _build_query_interpretation_record(
    *,
    question: str,
    query_rewrite_result: QueryRewritingResult | None,
    rewrite_preview_enabled: bool,
    answer_mode_result: AnswerModeResult,
) -> QueryInterpretationRecord:
    intent = (
        "product_guidance"
        if answer_mode_result.mode == "guidance"
        else _infer_query_intent(question)
    )
    strategy = query_rewrite_result.strategy if query_rewrite_result is not None else "original"
    complexity = _query_complexity(
        intent=intent,
        query_rewrite_result=query_rewrite_result,
        question=question,
    )
    preview_available = (
        rewrite_preview_enabled
        and query_rewrite_result is not None
        and (query_rewrite_result.rewriting_applied or query_rewrite_result.decomposition_applied)
    )
    rewritten_query_preview = (
        query_rewrite_result.primary_query
        if preview_available
        and query_rewrite_result is not None
        and query_rewrite_result.primary_query.strip()
        else None
    )
    sub_queries = (
        list(query_rewrite_result.sub_queries)
        if preview_available
        and query_rewrite_result is not None
        and query_rewrite_result.decomposition_applied
        else []
    )
    return QueryInterpretationRecord(
        answer_mode=answer_mode_result.mode,
        intent=intent,
        intent_label=(
            _guidance_label(answer_mode_result.topic)
            if answer_mode_result.mode == "guidance"
            else _QUERY_INTENT_LABELS.get(intent, "Lookup")
        ),
        complexity=complexity,
        retrieval_strategy=strategy,
        rewrite_preview_enabled=rewrite_preview_enabled,
        rewritten_query_preview=rewritten_query_preview,
        sub_queries=sub_queries,
        guidance_topic=answer_mode_result.topic,
    )


def _build_search_mode(
    *,
    hybrid_retrieval_enabled: bool,
    graph_context_result: GraphRetrievalResult,
) -> str:
    if graph_context_result.graph_context_used and hybrid_retrieval_enabled:
        return "hybrid+graph"
    if graph_context_result.graph_context_used:
        return "graph"
    if hybrid_retrieval_enabled:
        return "hybrid"
    return "vector"


def _build_retrieval_profile_scope(
    *,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    graph_context_result: GraphRetrievalResult,
    document_ids: list[UUID] | None,
) -> str:
    if payload.scope_mode == "none":
        return "none"
    if graph_context_result.graph_context_used:
        return "graph"
    if payload.source_scope is not None:
        if payload.source_scope.mode == "collections":
            return "selected collection"
        if payload.source_scope.mode in {"connector_sources", "connector_items"}:
            return "connector"
        if payload.source_scope.mode == "uploaded":
            return "document"
        if payload.source_scope.mode == "all" and (
            payload.source_scope.collection_ids
            or payload.source_scope.provider_keys
            or payload.source_scope.connection_ids
            or payload.source_scope.provider_source_ids
            or payload.source_scope.external_source_ids
            or payload.source_scope.external_item_ids
        ):
            return "document"
    if document_ids:
        return "document"
    if source_scope_result.label == "All sources":
        return "all documents"
    return "all documents"


def _build_retrieval_filters(
    *,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    document_ids: list[UUID] | None,
    graph_context_result: GraphRetrievalResult,
) -> list[str]:
    filters: list[str] = []
    if payload.scope_mode is not None:
        filters.append(f"scope_mode={payload.scope_mode}")
    if document_ids:
        filters.append(f"documents={len(document_ids)}")
    if payload.source_scope is not None:
        scope = payload.source_scope
        if scope.mode != "all":
            filters.append(f"source_scope={scope.mode}")
        if scope.collection_ids:
            filters.append(f"collections={len(scope.collection_ids)}")
        if scope.provider_keys:
            filters.append(f"providers={len(scope.provider_keys)}")
        if scope.connection_ids:
            filters.append(f"connections={len(scope.connection_ids)}")
        if scope.provider_source_ids:
            filters.append(f"provider_sources={len(scope.provider_source_ids)}")
        if scope.external_source_ids:
            filters.append(f"external_sources={len(scope.external_source_ids)}")
        if scope.external_item_ids:
            filters.append(f"external_items={len(scope.external_item_ids)}")
        if scope.document_types:
            filters.append(f"document_types={', '.join(scope.document_types[:3])}")
        if scope.sync_statuses:
            filters.append(f"sync_statuses={', '.join(scope.sync_statuses[:3])}")
    if graph_context_result.graph_context_used:
        filters.append("graph=enabled")
    if source_scope_result.label:
        filters.append(f"scope={source_scope_result.label}")
    # Keep the list short and readable in the trust panel.
    return filters[:8]
