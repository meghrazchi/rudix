"""Tests for F341 — dynamic retrieval strategy selection and self-discover routing.

Coverage:
- RetrievalStrategyRouter.route() for all 7 planner strategies
- Feature-flag constraint downgrading (hybrid off → vector, graph off → hybrid/vector)
- Profile-level override (admin)
- User-level override (when flag permits)
- User-level override blocked (when flag is off)
- "auto" profile override is treated as no-override
- Invalid override values are ignored
- Router failure fallback
- FeatureAvailability constraints
- RetrievalMethodRecord schema
- AnswerTrustMetadataResponse includes retrieval_method field
- _build_retrieval_method_record helper
- Privacy: internal reason strings never appear in trust metadata
"""

from __future__ import annotations

import pytest

from app.domains.chat.schemas.trust_metadata import (
    AnswerTrustMetadataResponse,
    RetrievalMethodRecord,
)
from app.domains.chat.services.retrieval_strategy_router import (
    FeatureAvailability,
    RetrievalStrategyRouter,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router() -> RetrievalStrategyRouter:
    return RetrievalStrategyRouter()


@pytest.fixture
def all_features() -> FeatureAvailability:
    return FeatureAvailability(
        hybrid_retrieval_enabled=True,
        graph_rag_enabled=True,
        parent_context_expansion_enabled=True,
        keyword_retrieval_enabled=True,
    )


@pytest.fixture
def vector_only_features() -> FeatureAvailability:
    return FeatureAvailability(
        hybrid_retrieval_enabled=False,
        graph_rag_enabled=False,
        parent_context_expansion_enabled=False,
        keyword_retrieval_enabled=False,
    )


# ---------------------------------------------------------------------------
# Auto-routing: strategy → method mapping
# ---------------------------------------------------------------------------


def test_legal_compliance_routes_to_hybrid(router, all_features):
    result = router.route(planner_strategy="legal_compliance", features=all_features)
    assert result.method == "hybrid"
    assert result.override_applied is False
    assert result.override_source is None


def test_policy_lookup_routes_to_keyword(router, all_features):
    result = router.route(planner_strategy="policy_lookup", features=all_features)
    assert result.method == "keyword"


def test_comparison_routes_to_hybrid(router, all_features):
    result = router.route(planner_strategy="comparison", features=all_features)
    assert result.method == "hybrid"


def test_incident_decision_support_routes_to_hybrid(router, all_features):
    result = router.route(planner_strategy="incident_decision_support", features=all_features)
    assert result.method == "hybrid"


def test_table_heavy_routes_to_table_aware(router, all_features):
    result = router.route(planner_strategy="table_heavy", features=all_features)
    assert result.method == "table_aware"


def test_graph_assisted_routes_to_graph_rag(router, all_features):
    result = router.route(planner_strategy="graph_assisted", features=all_features)
    assert result.method == "graph_rag"


def test_connector_search_routes_to_connector_aware(router, all_features):
    result = router.route(planner_strategy="connector_search", features=all_features)
    assert result.method == "connector_aware"


def test_troubleshooting_routes_to_hybrid(router, all_features):
    result = router.route(planner_strategy="troubleshooting", features=all_features)
    assert result.method == "hybrid"


def test_summary_routes_to_parent_child(router, all_features):
    result = router.route(planner_strategy="summary", features=all_features)
    assert result.method == "parent_child"


def test_standard_routes_to_hybrid_when_available(router, all_features):
    result = router.route(planner_strategy="standard", features=all_features)
    assert result.method == "hybrid"


def test_unknown_strategy_falls_back_to_hybrid(router, all_features):
    result = router.route(planner_strategy="unknown_xyz", features=all_features)
    assert result.method == "hybrid"


# ---------------------------------------------------------------------------
# Feature constraint downgrading
# ---------------------------------------------------------------------------


def test_hybrid_downgraded_to_vector_when_hybrid_disabled(router, vector_only_features):
    result = router.route(planner_strategy="legal_compliance", features=vector_only_features)
    assert result.method == "vector"


def test_table_aware_downgraded_to_vector_when_hybrid_disabled(router, vector_only_features):
    result = router.route(planner_strategy="table_heavy", features=vector_only_features)
    assert result.method == "vector"


def test_graph_rag_downgraded_to_hybrid_when_graph_disabled_hybrid_available(router):
    features = FeatureAvailability(
        hybrid_retrieval_enabled=True,
        graph_rag_enabled=False,
        parent_context_expansion_enabled=True,
        keyword_retrieval_enabled=True,
    )
    result = router.route(planner_strategy="graph_assisted", features=features)
    assert result.method == "hybrid"


def test_graph_rag_downgraded_to_vector_when_both_disabled(router, vector_only_features):
    result = router.route(planner_strategy="graph_assisted", features=vector_only_features)
    assert result.method == "vector"


def test_parent_child_downgraded_to_vector_when_expansion_disabled(router):
    features = FeatureAvailability(
        hybrid_retrieval_enabled=True,
        graph_rag_enabled=True,
        parent_context_expansion_enabled=False,
        keyword_retrieval_enabled=True,
    )
    result = router.route(planner_strategy="summary", features=features)
    assert result.method == "vector"


def test_keyword_downgraded_to_vector_when_keyword_disabled(router):
    features = FeatureAvailability(
        hybrid_retrieval_enabled=False,
        graph_rag_enabled=False,
        parent_context_expansion_enabled=True,
        keyword_retrieval_enabled=False,
    )
    result = router.route(planner_strategy="policy_lookup", features=features)
    assert result.method == "vector"


def test_connector_aware_downgraded_to_vector_when_hybrid_disabled(router, vector_only_features):
    result = router.route(planner_strategy="connector_search", features=vector_only_features)
    assert result.method == "vector"


# ---------------------------------------------------------------------------
# Profile-level (admin) override
# ---------------------------------------------------------------------------


def test_profile_override_forces_vector(router, all_features):
    result = router.route(
        planner_strategy="legal_compliance",
        features=all_features,
        profile_override="vector",
    )
    assert result.method == "vector"
    assert result.override_applied is True
    assert result.override_source == "rag_profile"


def test_profile_override_forces_keyword(router, all_features):
    result = router.route(
        planner_strategy="standard",
        features=all_features,
        profile_override="keyword",
    )
    assert result.method == "keyword"
    assert result.override_source == "rag_profile"


def test_profile_override_auto_treated_as_no_override(router, all_features):
    result = router.route(
        planner_strategy="legal_compliance",
        features=all_features,
        profile_override="auto",
    )
    assert result.override_applied is False
    assert result.method == "hybrid"


def test_profile_override_invalid_value_ignored(router, all_features):
    result = router.route(
        planner_strategy="legal_compliance",
        features=all_features,
        profile_override="totally_invalid",
    )
    assert result.override_applied is False
    assert result.method == "hybrid"


# ---------------------------------------------------------------------------
# User-level override
# ---------------------------------------------------------------------------


def test_user_override_honoured_when_flag_enabled(router, all_features):
    result = router.route(
        planner_strategy="legal_compliance",
        features=all_features,
        request_override="vector",
        allow_user_override=True,
    )
    assert result.method == "vector"
    assert result.override_applied is True
    assert result.override_source == "user"


def test_user_override_blocked_when_flag_disabled(router, all_features):
    result = router.route(
        planner_strategy="legal_compliance",
        features=all_features,
        request_override="vector",
        allow_user_override=False,
    )
    assert result.override_applied is False
    assert result.method == "hybrid"


def test_user_override_invalid_value_ignored(router, all_features):
    result = router.route(
        planner_strategy="standard",
        features=all_features,
        request_override="not_a_real_method",
        allow_user_override=True,
    )
    assert result.override_applied is False


def test_user_override_takes_precedence_over_profile_override(router, all_features):
    result = router.route(
        planner_strategy="standard",
        features=all_features,
        profile_override="keyword",
        request_override="vector",
        allow_user_override=True,
    )
    assert result.method == "vector"
    assert result.override_source == "user"


# ---------------------------------------------------------------------------
# Override + feature constraint interaction
# ---------------------------------------------------------------------------


def test_profile_override_hybrid_downgraded_when_hybrid_disabled(router, vector_only_features):
    result = router.route(
        planner_strategy="standard",
        features=vector_only_features,
        profile_override="hybrid",
    )
    assert result.method == "vector"
    assert result.override_applied is True


# ---------------------------------------------------------------------------
# Method labels
# ---------------------------------------------------------------------------


def test_method_label_populated(router, all_features):
    result = router.route(planner_strategy="legal_compliance", features=all_features)
    assert result.method_label == "Hybrid search"


def test_graph_rag_label(router, all_features):
    result = router.route(planner_strategy="graph_assisted", features=all_features)
    assert result.method_label == "Graph-assisted search"


def test_parent_child_label(router, all_features):
    result = router.route(planner_strategy="summary", features=all_features)
    assert result.method_label == "Context-expanded search"


# ---------------------------------------------------------------------------
# Fallback on router error
# ---------------------------------------------------------------------------


def test_router_returns_fallback_on_error():
    """Simulate an error by passing a features object that raises on access."""

    class BrokenFeatures:
        @property
        def hybrid_retrieval_enabled(self):
            raise RuntimeError("simulated error")

    router = RetrievalStrategyRouter()
    result = router.route(planner_strategy="standard", features=BrokenFeatures())  # type: ignore[arg-type]
    assert result.method == "auto_fallback"
    assert result.override_applied is False


# ---------------------------------------------------------------------------
# Privacy: internal reason not in public record
# ---------------------------------------------------------------------------


def test_reason_not_in_retrieval_method_record(router, all_features):
    """Internal routing reason must not appear in the public RetrievalMethodRecord."""
    from app.interfaces.http.chat import _build_retrieval_method_record

    route_result = router.route(planner_strategy="legal_compliance", features=all_features)
    record = _build_retrieval_method_record(route_result)
    # Ensure 'reason' is not a field on the Pydantic model
    assert not hasattr(record, "reason")
    record_dict = record.model_dump()
    assert "reason" not in record_dict


# ---------------------------------------------------------------------------
# RetrievalMethodRecord schema
# ---------------------------------------------------------------------------


def test_retrieval_method_record_defaults():
    rec = RetrievalMethodRecord()
    assert rec.method == "vector"
    assert rec.method_label == "Vector search"
    assert rec.override_applied is False
    assert rec.override_source is None
    assert rec.routing_latency_ms == 0


def test_retrieval_method_record_with_values():
    rec = RetrievalMethodRecord(
        method="hybrid",
        method_label="Hybrid search",
        override_applied=True,
        override_source="rag_profile",
        routing_latency_ms=1,
    )
    assert rec.method == "hybrid"
    assert rec.override_source == "rag_profile"


def test_answer_trust_metadata_has_retrieval_method_field():
    """AnswerTrustMetadataResponse must include a retrieval_method field."""

    from app.domains.chat.schemas.trust_metadata import (
        AnswerTrustMetadataResponse,
    )

    fields = AnswerTrustMetadataResponse.model_fields
    assert "retrieval_method" in fields


def test_retrieval_method_default_in_trust_metadata():
    """retrieval_method defaults to an empty RetrievalMethodRecord (backward-compat)."""
    fields = AnswerTrustMetadataResponse.model_fields
    retrieval_method_field = fields["retrieval_method"]
    assert retrieval_method_field.default_factory is not None  # type: ignore[union-attr]
    default = retrieval_method_field.default_factory()  # type: ignore[misc]
    assert isinstance(default, RetrievalMethodRecord)


# ---------------------------------------------------------------------------
# _build_retrieval_method_record helper
# ---------------------------------------------------------------------------


def test_build_retrieval_method_record_none_returns_default(router, all_features):
    from app.interfaces.http.chat import _build_retrieval_method_record

    record = _build_retrieval_method_record(None)
    assert isinstance(record, RetrievalMethodRecord)
    assert record.method == "vector"


def test_build_retrieval_method_record_from_result(router, all_features):
    from app.interfaces.http.chat import _build_retrieval_method_record

    route_result = router.route(
        planner_strategy="graph_assisted",
        features=all_features,
        profile_override="graph_rag",
    )
    record = _build_retrieval_method_record(route_result)
    assert record.method == "graph_rag"
    assert record.method_label == "Graph-assisted search"
    assert record.override_applied is True
    assert record.override_source == "rag_profile"
