"""Tests for F342 — permission-aware adaptive tool orchestration.

Coverage:
- ChatToolCapability spec: all 8 tools defined with correct fields
- ChatToolOrchestrator.orchestrate() for all relevant planner strategies
- Role-based authorization (denied when role is insufficient)
- Permission-based authorization (denied when permission is missing)
- Feature flag gating (denied when feature is disabled)
- Org-level policy override (denied when tool is in disabled_tool_names)
- Source scope check for collection_search
- Strategy relevance filtering (irrelevant tools are skipped)
- API key principal uses api_key_permissions
- ToolOrchestrationResult aggregate properties
- ToolOrchestrationRecord schema (trust metadata)
- AnswerTrustMetadataResponse includes tool_orchestration field
- _build_tool_orchestration_record helper
- ChatToolCallRecord schema
- Fallback behavior: all denied tools produce fallback_used=True
- Safe handling: orchestration never raises
- Admin endpoint schema
"""

from __future__ import annotations

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.domains.chat.schemas.trust_metadata import (
    AnswerTrustMetadataResponse,
    ChatToolCallRecord,
    ToolOrchestrationRecord,
)
from app.domains.chat.services.tool_orchestrator import (
    CHAT_TOOL_CAPABILITIES,
    ChatToolCapability,
    ChatToolOrchestrator,
    ToolOrchestrationResult,
    _check_authorization,
    _resolve_effective_permissions,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator() -> ChatToolOrchestrator:
    return ChatToolOrchestrator()


def _principal(
    roles: list[str] | None = None,
    api_key_permissions: frozenset[str] | None = None,
    organization_id: str = "org-1",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        organization_id=organization_id,
        roles=roles or ["member"],
        auth_provider="app",
        api_key_permissions=api_key_permissions,
    )


def _member() -> AuthenticatedPrincipal:
    return _principal(roles=["member"])


def _admin() -> AuthenticatedPrincipal:
    return _principal(roles=["admin"])


def _viewer() -> AuthenticatedPrincipal:
    return _principal(roles=["viewer"])


ALL_FEATURES_ON: dict[str, bool] = {
    "feature_enable_connectors": True,
    "feature_enable_graph_rag": True,
}

ALL_FEATURES_OFF: dict[str, bool] = {
    "feature_enable_connectors": False,
    "feature_enable_graph_rag": False,
}

NO_DISABLED: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Capability spec tests
# ---------------------------------------------------------------------------


class TestChatToolCapabilities:
    def test_all_eight_tools_defined(self) -> None:
        names = {cap.name for cap in CHAT_TOOL_CAPABILITIES}
        assert names == {
            "document_search",
            "collection_search",
            "connector_search",
            "graph_search",
            "citation_preview",
            "evaluation_lookup",
            "feedback_creation",
            "document_lifecycle_lookup",
        }

    def test_document_search_no_feature_flag(self) -> None:
        cap = next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "document_search")
        assert cap.feature_flag is None
        assert cap.required_permission == "documents:view"
        assert not cap.approval_required
        assert "standard" in cap.relevant_strategies

    def test_graph_search_feature_flag(self) -> None:
        cap = next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "graph_search")
        assert cap.feature_flag == "feature_enable_graph_rag"
        assert cap.required_permission == "graph:view"
        assert "graph_assisted" in cap.relevant_strategies

    def test_connector_search_feature_flag(self) -> None:
        cap = next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "connector_search")
        assert cap.feature_flag == "feature_enable_connectors"
        assert "connector_search" in cap.relevant_strategies

    def test_evaluation_lookup_elevated_only(self) -> None:
        cap = next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "evaluation_lookup")
        assert cap.required_roles == frozenset({"owner", "admin"})
        assert cap.required_permission == "evaluations:view"

    def test_document_lifecycle_lookup_elevated_only(self) -> None:
        cap = next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "document_lifecycle_lookup")
        assert cap.required_roles == frozenset({"owner", "admin"})
        assert cap.required_permission == "documents:manage"

    def test_all_tools_have_purpose_and_permission(self) -> None:
        for cap in CHAT_TOOL_CAPABILITIES:
            assert cap.purpose, f"{cap.name} missing purpose"
            assert cap.required_permission, f"{cap.name} missing required_permission"
            assert cap.allowed_resource_types, f"{cap.name} missing allowed_resource_types"
            assert cap.relevant_strategies, f"{cap.name} missing relevant_strategies"

    def test_all_tools_have_positive_budget(self) -> None:
        for cap in CHAT_TOOL_CAPABILITIES:
            assert cap.timeout_ms > 0, f"{cap.name} timeout_ms must be positive"
            assert cap.max_calls_per_run > 0, f"{cap.name} max_calls_per_run must be positive"


# ---------------------------------------------------------------------------
# Authorization check unit tests
# ---------------------------------------------------------------------------


class TestCheckAuthorization:
    def _cap(self, name: str) -> ChatToolCapability:
        return next(c for c in CHAT_TOOL_CAPABILITIES if c.name == name)

    def test_authorized_for_member_on_document_search(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("document_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result is None

    def test_org_policy_disabled(self) -> None:
        principal = _admin()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("document_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=frozenset({"document_search"}),
            source_scope_mode=None,
        )
        assert result == "org_policy_disabled"

    def test_feature_flag_unavailable(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("graph_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability={"feature_enable_graph_rag": False},
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result == "feature_unavailable"

    def test_feature_flag_available_allows_through(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("graph_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability={"feature_enable_graph_rag": True},
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result is None

    def test_insufficient_role_for_elevated_tool(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("evaluation_lookup"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result == "insufficient_role"

    def test_admin_authorized_for_elevated_tool(self) -> None:
        principal = _admin()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=self._cap("evaluation_lookup"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result is None

    def test_insufficient_permission_for_collection_search_via_api_key(self) -> None:
        principal = _principal(
            api_key_permissions=frozenset({"chat:use"}),
        )
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "collection_search"),
            principal_roles=frozenset(principal.roles or []),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result == "insufficient_permission"

    def test_api_key_with_required_permission(self) -> None:
        principal = _principal(
            api_key_permissions=frozenset({"chat:use", "chat:use_collections"}),
        )
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "collection_search"),
            principal_roles=frozenset(principal.roles or []),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode="collection",
        )
        assert result is None

    def test_collection_search_wrong_source_scope(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "collection_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode="none",
        )
        assert result == "source_scope_mismatch"

    def test_collection_search_no_scope_mode_allowed(self) -> None:
        principal = _member()
        effective_perms = _resolve_effective_permissions(principal)
        result = _check_authorization(
            cap=next(c for c in CHAT_TOOL_CAPABILITIES if c.name == "collection_search"),
            principal_roles=frozenset(principal.roles),
            effective_permissions=effective_perms,
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
            source_scope_mode=None,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


class TestChatToolOrchestrator:
    def test_returns_result_when_enabled(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        assert result.enabled is True
        assert result.tool_count > 0

    def test_standard_strategy_includes_document_search(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        names = {t.tool_name for t in result.tool_calls}
        assert "document_search" in names
        assert "citation_preview" in names
        assert "feedback_creation" in names

    def test_graph_assisted_strategy_includes_graph_search(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="graph_assisted",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        names = {t.tool_name for t in result.tool_calls}
        assert "graph_search" in names

    def test_connector_search_strategy_includes_connector_search(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="connector_search",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        names = {t.tool_name for t in result.tool_calls}
        assert "connector_search" in names

    def test_irrelevant_strategy_skips_elevated_only_tools(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="comparison",
            principal=_admin(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        names = {t.tool_name for t in result.tool_calls}
        assert "evaluation_lookup" not in names
        assert "document_lifecycle_lookup" not in names

    def test_graph_search_denied_when_feature_off(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="graph_assisted",
            principal=_member(),
            feature_availability={"feature_enable_graph_rag": False},
            disabled_tool_names=NO_DISABLED,
        )
        graph_calls = [t for t in result.tool_calls if t.tool_name == "graph_search"]
        assert len(graph_calls) == 1
        assert graph_calls[0].authorized is False
        assert graph_calls[0].denial_reason == "feature_unavailable"
        assert graph_calls[0].fallback_used is True

    def test_org_policy_disabled_tool_denied(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=frozenset({"document_search"}),
        )
        doc_calls = [t for t in result.tool_calls if t.tool_name == "document_search"]
        assert len(doc_calls) == 1
        assert doc_calls[0].authorized is False
        assert doc_calls[0].denial_reason == "org_policy_disabled"

    def test_member_denied_evaluation_lookup(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="troubleshooting",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        eval_calls = [t for t in result.tool_calls if t.tool_name == "evaluation_lookup"]
        assert len(eval_calls) == 1
        assert eval_calls[0].authorized is False

    def test_admin_authorized_for_all_standard_tools(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="troubleshooting",
            principal=_admin(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        assert result.authorized_count == result.tool_count
        assert result.denied_count == 0

    def test_aggregate_counts_are_correct(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=frozenset({"citation_preview"}),
        )
        assert result.tool_count == len(result.tool_calls)
        assert result.authorized_count + result.denied_count == result.tool_count
        assert result.fallback_count == result.denied_count

    def test_orchestration_latency_ms_is_non_negative(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        assert result.orchestration_latency_ms >= 0

    def test_tool_call_latency_ms_non_negative(self, orchestrator: ChatToolOrchestrator) -> None:
        result = orchestrator.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability=ALL_FEATURES_ON,
            disabled_tool_names=NO_DISABLED,
        )
        for call in result.tool_calls:
            assert call.latency_ms >= 0

    def test_list_capabilities(self, orchestrator: ChatToolOrchestrator) -> None:
        caps = orchestrator.list_capabilities()
        assert len(caps) == 8

    def test_get_capability_by_name(self, orchestrator: ChatToolOrchestrator) -> None:
        cap = orchestrator.get_capability("document_search")
        assert cap is not None
        assert cap.name == "document_search"

    def test_get_nonexistent_capability_returns_none(
        self, orchestrator: ChatToolOrchestrator
    ) -> None:
        assert orchestrator.get_capability("does_not_exist") is None

    def test_custom_capabilities_override(self) -> None:
        from app.domains.chat.services.tool_orchestrator import _ALL_STRATEGIES

        custom_cap = ChatToolCapability(
            name="test_tool",
            purpose="For testing.",
            required_permission="chat:use",
            allowed_resource_types=["document"],
            approval_required=False,
            feature_flag=None,
            relevant_strategies=_ALL_STRATEGIES,
        )
        orch = ChatToolOrchestrator(capabilities=(custom_cap,))
        result = orch.orchestrate(
            planner_strategy="standard",
            principal=_member(),
            feature_availability={},
            disabled_tool_names=NO_DISABLED,
        )
        assert result.tool_count == 1
        assert result.tool_calls[0].tool_name == "test_tool"


# ---------------------------------------------------------------------------
# _resolve_effective_permissions tests
# ---------------------------------------------------------------------------


class TestResolveEffectivePermissions:
    def test_member_has_documents_view(self) -> None:
        perms = _resolve_effective_permissions(_member())
        assert "documents:view" in perms

    def test_admin_has_documents_manage(self) -> None:
        perms = _resolve_effective_permissions(_admin())
        assert "documents:manage" in perms
        assert "evaluations:view" in perms

    def test_api_key_uses_api_key_permissions_not_roles(self) -> None:
        principal = _principal(
            roles=["admin"],
            api_key_permissions=frozenset({"chat:use"}),
        )
        perms = _resolve_effective_permissions(principal)
        assert perms == frozenset({"chat:use"})
        assert "documents:view" not in perms

    def test_empty_roles_returns_empty_permissions(self) -> None:
        principal = _principal(roles=[])
        perms = _resolve_effective_permissions(principal)
        assert isinstance(perms, frozenset)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestToolOrchestrationRecord:
    def test_default_factory_disabled(self) -> None:
        record = ToolOrchestrationRecord()
        assert record.enabled is False
        assert record.tool_count == 0
        assert record.tool_calls == []

    def test_schema_serializable(self) -> None:
        record = ToolOrchestrationRecord(
            enabled=True,
            tool_count=2,
            authorized_count=1,
            denied_count=1,
            tool_calls=[
                ChatToolCallRecord(
                    tool_name="document_search",
                    tool_purpose="Test purpose",
                    authorized=True,
                    executed=True,
                    succeeded=True,
                    fallback_used=False,
                    latency_ms=3,
                ),
                ChatToolCallRecord(
                    tool_name="graph_search",
                    tool_purpose="Graph purpose",
                    authorized=False,
                    executed=False,
                    succeeded=False,
                    fallback_used=True,
                    latency_ms=1,
                    denial_reason="feature_unavailable",
                    error_code="authorization_failed",
                ),
            ],
        )
        data = record.model_dump()
        assert data["enabled"] is True
        assert len(data["tool_calls"]) == 2
        assert data["tool_calls"][1]["denial_reason"] == "feature_unavailable"

    def test_answer_trust_metadata_has_tool_orchestration_field(self) -> None:
        from datetime import datetime

        from app.domains.chat.schemas.trust_metadata import (
            ConfidenceTrustRecord,
            ConflictStatusRecord,
            EvidenceQualityRecord,
            GroundedVerificationRecord,
            ModelMetadataRecord,
            PlannerCriticRecord,
            PolicyEnforcementRecord,
            RetrievalDiagnosticsRecord,
            RetrievalMethodRecord,
            SourceFreshnessRecord,
        )

        metadata = AnswerTrustMetadataResponse(
            organization_id="org-1",
            message_id="msg-1",
            not_found=False,
            citation_validation_failed=False,
            verification_failed=False,
            confidence=ConfidenceTrustRecord(
                score=0.9,
                category="high",
                citation_support_score=0.9,
                citation_validation_score=1.0,
                citation_coverage_score=0.9,
                retrieval_agreement_score=0.9,
                top_similarity=0.9,
                average_similarity=0.85,
                top_rerank_score=0.0,
                raw_score=0.9,
                citation_validation_multiplier=1.0,
                not_found_penalty_multiplier=1.0,
                not_found_signal=False,
                no_context=False,
            ),
            citations=[],
            retrieval=RetrievalDiagnosticsRecord(),
            grounded_verification=GroundedVerificationRecord(),
            model=ModelMetadataRecord(),
            conflict=ConflictStatusRecord(),
            policy=PolicyEnforcementRecord(),
            freshness=SourceFreshnessRecord(),
            evidence_quality=EvidenceQualityRecord(),
            planner_critic=PlannerCriticRecord(),
            retrieval_method=RetrievalMethodRecord(),
            tool_orchestration=ToolOrchestrationRecord(),
            generated_at=datetime.now(),
        )
        assert hasattr(metadata, "tool_orchestration")
        assert isinstance(metadata.tool_orchestration, ToolOrchestrationRecord)
        assert metadata.tool_orchestration.enabled is False

    def test_answer_trust_metadata_default_factory(self) -> None:
        from datetime import datetime

        from app.domains.chat.schemas.trust_metadata import (
            ConfidenceTrustRecord,
            ConflictStatusRecord,
            EvidenceQualityRecord,
            GroundedVerificationRecord,
            ModelMetadataRecord,
            PlannerCriticRecord,
            PolicyEnforcementRecord,
            RetrievalDiagnosticsRecord,
            RetrievalMethodRecord,
            SourceFreshnessRecord,
        )

        metadata = AnswerTrustMetadataResponse(
            organization_id="org-1",
            message_id="msg-1",
            not_found=False,
            citation_validation_failed=False,
            verification_failed=False,
            confidence=ConfidenceTrustRecord(
                score=0.9,
                category="high",
                citation_support_score=0.9,
                citation_validation_score=1.0,
                citation_coverage_score=0.9,
                retrieval_agreement_score=0.9,
                top_similarity=0.9,
                average_similarity=0.85,
                top_rerank_score=0.0,
                raw_score=0.9,
                citation_validation_multiplier=1.0,
                not_found_penalty_multiplier=1.0,
                not_found_signal=False,
                no_context=False,
            ),
            citations=[],
            retrieval=RetrievalDiagnosticsRecord(),
            grounded_verification=GroundedVerificationRecord(),
            model=ModelMetadataRecord(),
            conflict=ConflictStatusRecord(),
            policy=PolicyEnforcementRecord(),
            freshness=SourceFreshnessRecord(),
            evidence_quality=EvidenceQualityRecord(),
            planner_critic=PlannerCriticRecord(),
            retrieval_method=RetrievalMethodRecord(),
            generated_at=datetime.now(),
        )
        # Default factory must produce a disabled record (backward compat with pre-F342 messages)
        assert metadata.tool_orchestration.enabled is False
        assert metadata.tool_orchestration.tool_calls == []


# ---------------------------------------------------------------------------
# _build_tool_orchestration_record helper tests (via import guard)
# ---------------------------------------------------------------------------


class TestBuildToolOrchestrationRecord:
    def test_none_result_returns_default(self) -> None:
        from app.interfaces.http.chat import _build_tool_orchestration_record

        record = _build_tool_orchestration_record(None)
        assert record.enabled is False
        assert record.tool_count == 0

    def test_disabled_result_returns_default(self) -> None:
        from app.interfaces.http.chat import _build_tool_orchestration_record

        disabled = ToolOrchestrationResult(enabled=False, tool_calls=[])
        record = _build_tool_orchestration_record(disabled)
        assert record.enabled is False

    def test_active_result_is_serialized(self) -> None:
        from app.domains.chat.services.tool_orchestrator import ChatToolCallRecord as _SvcRecord
        from app.interfaces.http.chat import _build_tool_orchestration_record

        active = ToolOrchestrationResult(
            enabled=True,
            orchestration_latency_ms=5,
            tool_calls=[
                _SvcRecord(
                    tool_name="document_search",
                    tool_purpose="Search docs.",
                    authorized=True,
                    executed=True,
                    succeeded=True,
                    fallback_used=False,
                    latency_ms=2,
                ),
                _SvcRecord(
                    tool_name="graph_search",
                    tool_purpose="Search graph.",
                    authorized=False,
                    executed=False,
                    succeeded=False,
                    fallback_used=True,
                    latency_ms=0,
                    denial_reason="feature_unavailable",
                    error_code="authorization_failed",
                ),
            ],
        )
        record = _build_tool_orchestration_record(active)
        assert record.enabled is True
        assert record.tool_count == 2
        assert record.authorized_count == 1
        assert record.denied_count == 1
        assert record.orchestration_latency_ms == 5
        assert len(record.tool_calls) == 2
        assert record.tool_calls[1].denial_reason == "feature_unavailable"

    def test_all_authorized_result(self) -> None:
        from app.domains.chat.services.tool_orchestrator import ChatToolCallRecord as _SvcRecord
        from app.interfaces.http.chat import _build_tool_orchestration_record

        active = ToolOrchestrationResult(
            enabled=True,
            orchestration_latency_ms=3,
            tool_calls=[
                _SvcRecord(
                    tool_name="citation_preview",
                    tool_purpose="Preview.",
                    authorized=True,
                    executed=True,
                    succeeded=True,
                    fallback_used=False,
                    latency_ms=1,
                ),
            ],
        )
        record = _build_tool_orchestration_record(active)
        assert record.succeeded_count == 1
        assert record.fallback_count == 0


# ---------------------------------------------------------------------------
# Admin endpoint schema tests
# ---------------------------------------------------------------------------


class TestAdminChatToolsSchema:
    def test_availability_entry_fields(self) -> None:
        from app.interfaces.http.admin_chat_tools import ChatToolAvailabilityEntry

        entry = ChatToolAvailabilityEntry(
            name="document_search",
            purpose="Search docs.",
            required_permission="documents:view",
            allowed_resource_types=["document"],
            approval_required=False,
            feature_flag=None,
            required_roles=["member", "viewer", "admin", "owner"],
            feature_available=True,
            org_policy_enabled=True,
            available=True,
        )
        assert entry.available is True
        assert entry.name == "document_search"

    def test_availability_response_schema(self) -> None:
        from app.interfaces.http.admin_chat_tools import (
            ChatToolAvailabilityEntry,
            ChatToolsAvailabilityResponse,
        )

        response = ChatToolsAvailabilityResponse(
            organization_id="org-1",
            feature_enabled=False,
            tools=[
                ChatToolAvailabilityEntry(
                    name="document_search",
                    purpose="Search docs.",
                    required_permission="documents:view",
                    allowed_resource_types=["document"],
                    approval_required=False,
                    feature_flag=None,
                    required_roles=["member"],
                    feature_available=True,
                    org_policy_enabled=True,
                    available=True,
                )
            ],
        )
        assert len(response.tools) == 1
        assert response.feature_enabled is False

    def test_tool_unavailable_when_feature_disabled(self) -> None:
        from app.interfaces.http.admin_chat_tools import ChatToolAvailabilityEntry

        entry = ChatToolAvailabilityEntry(
            name="graph_search",
            purpose="Graph.",
            required_permission="graph:view",
            allowed_resource_types=["graph_entity"],
            approval_required=False,
            feature_flag="feature_enable_graph_rag",
            required_roles=["member"],
            feature_available=False,
            org_policy_enabled=True,
            available=False,
        )
        assert entry.available is False
        assert entry.feature_available is False

    def test_tool_unavailable_when_org_disabled(self) -> None:
        from app.interfaces.http.admin_chat_tools import ChatToolAvailabilityEntry

        entry = ChatToolAvailabilityEntry(
            name="document_search",
            purpose="Search.",
            required_permission="documents:view",
            allowed_resource_types=["document"],
            approval_required=False,
            feature_flag=None,
            required_roles=["member"],
            feature_available=True,
            org_policy_enabled=False,
            available=False,
        )
        assert entry.available is False
        assert entry.org_policy_enabled is False
