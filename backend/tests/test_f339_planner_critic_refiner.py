"""Tests for the F339 planner-critic-refiner pipeline.

Covers:
- AnswerPlannerService: strategy classification, high_risk flag, error fallback
- AnswerCriticService: warning aggregation, severity, requires_refiner, instruction
- AnswerRefinerService: LLM call + JSON parse, fallback on error, draft_changed flag
- Trust metadata: PlannerCriticRecord / CriticWarningRecord schema
- Compliance, legal, HR, and comparison answer tests
- Unsupported claim removal via refiner
- Pipeline integration helpers: _resolve_planner_critic_controls, _build_planner_critic_record
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.chat.schemas.trust_metadata import (
    CriticWarningRecord,
    PlannerCriticRecord,
)
from app.domains.chat.services.answer_critic_service import (
    AnswerCriticService,
    CriticResult,
    CriticWarning,
    _build_refiner_instruction,
)
from app.domains.chat.services.answer_planner_service import (
    AnswerPlannerService,
    PlannerResult,
)
from app.domains.chat.services.answer_refiner_service import (
    AnswerRefinerService,
    RefinerResult,
    _build_refiner_prompt,
)


# ===========================================================================
# AnswerPlannerService
# ===========================================================================


class TestAnswerPlannerService:
    def setup_method(self):
        self.planner = AnswerPlannerService()

    # Strategy detection

    def test_legal_compliance_gdpr(self):
        result = self.planner.classify(question="What does our GDPR policy require?")
        assert result.strategy == "legal_compliance"
        assert result.high_risk is True

    def test_legal_compliance_contract(self):
        result = self.planner.classify(question="Review the contract liability clause.")
        assert result.strategy == "legal_compliance"

    def test_legal_compliance_soc2(self):
        result = self.planner.classify(question="What controls satisfy SOC2 compliance?")
        assert result.strategy == "legal_compliance"

    def test_policy_lookup(self):
        result = self.planner.classify(question="What is our expense policy?")
        assert result.strategy == "policy_lookup"
        assert result.high_risk is True

    def test_policy_lookup_hr(self):
        result = self.planner.classify(question="How many days of parental leave are permitted?")
        assert result.strategy == "policy_lookup"

    def test_comparison(self):
        result = self.planner.classify(question="Compare option A vs option B.")
        assert result.strategy == "comparison"
        assert result.high_risk is True

    def test_comparison_difference(self):
        result = self.planner.classify(question="What is the difference between RBAC and ABAC?")
        assert result.strategy == "comparison"

    def test_comparison_pros_cons(self):
        result = self.planner.classify(question="Pros and cons of using Kafka vs RabbitMQ?")
        assert result.strategy == "comparison"

    def test_table_heavy_detected(self):
        result = self.planner.classify(question="Show all users.", table_query_detected=True)
        assert result.strategy == "table_heavy"
        assert result.high_risk is False

    def test_table_heavy_question(self):
        result = self.planner.classify(question="List all employees and their departments.")
        assert result.strategy == "table_heavy"

    def test_graph_assisted(self):
        result = self.planner.classify(
            question="Find related entities.", graph_context_available=True
        )
        assert result.strategy == "graph_assisted"
        assert result.high_risk is False

    def test_connector_search(self):
        result = self.planner.classify(
            question="Search Jira tickets about deployment.", connector_search_scope=True
        )
        assert result.strategy == "connector_search"
        assert result.high_risk is False

    def test_standard_fallback(self):
        result = self.planner.classify(question="What is the capital of France?")
        assert result.strategy == "standard"
        assert result.high_risk is False

    # Priority ordering

    def test_legal_beats_policy(self):
        result = self.planner.classify(question="Our GDPR policy must comply with regulation.")
        assert result.strategy == "legal_compliance"

    def test_legal_beats_comparison(self):
        result = self.planner.classify(
            question="Compare the liability vs indemnification clauses in the contract."
        )
        assert result.strategy == "legal_compliance"

    def test_policy_beats_table(self):
        result = self.planner.classify(question="List all rules we are required to follow.")
        assert result.strategy == "policy_lookup"

    # Custom high-risk strategies

    def test_custom_high_risk_strategies(self):
        result = self.planner.classify(
            question="Graph entity search?",
            graph_context_available=True,
            high_risk_strategies_override=frozenset({"graph_assisted"}),
        )
        assert result.strategy == "graph_assisted"
        assert result.high_risk is True

    def test_empty_high_risk_strategies(self):
        result = self.planner.classify(
            question="Our GDPR policy.",
            high_risk_strategies_override=frozenset(),
        )
        assert result.strategy == "legal_compliance"
        assert result.high_risk is False

    # Error fallback

    def test_fallback_on_exception(self):
        with patch(
            "app.domains.chat.services.answer_planner_service._LEGAL_COMPLIANCE_RE.search",
            side_effect=RuntimeError("boom"),
        ):
            result = self.planner.classify(question="GDPR compliance required.")
        assert result.strategy == "standard"
        assert result.high_risk is False

    # Latency tracking

    def test_latency_ms_is_non_negative(self):
        result = self.planner.classify(question="Test question")
        assert result.latency_ms >= 0


# ===========================================================================
# AnswerCriticService
# ===========================================================================


class TestAnswerCriticService:
    def setup_method(self):
        self.critic = AnswerCriticService()

    def test_no_warnings_when_clean(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=5,
            citation_count=3,
        )
        assert result.severity == "none"
        assert result.warnings == []
        assert result.requires_refiner is False

    def test_no_sources_found(self):
        result = self.critic.evaluate(not_found=True, selected_chunk_count=0, citation_count=0)
        assert any(w.code == "no_sources_found" for w in result.warnings)
        assert result.severity == "high"
        assert result.requires_refiner is True

    def test_unsupported_claims_from_verifier(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            gv_applied=True,
            gv_unsupported_count=2,
        )
        assert any(w.code == "citation_unsupported" for w in result.warnings)
        assert result.severity == "high"
        assert result.requires_refiner is True

    def test_conflicting_sources_from_conflict_detection(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            conflict_detected=True,
        )
        assert any(w.code == "source_conflict" for w in result.warnings)
        assert result.severity == "high"
        assert result.requires_refiner is True

    def test_conflicting_sources_from_verifier(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            gv_applied=True,
            gv_conflicting_count=1,
        )
        assert any(w.code == "source_conflict" for w in result.warnings)

    def test_missing_evidence_medium_severity(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            gv_applied=True,
            gv_not_enough_evidence_count=3,
        )
        assert any(w.code == "missing_evidence" for w in result.warnings)
        assert result.severity == "medium"
        assert result.requires_refiner is True

    def test_stale_sources_low_severity(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=3,
            freshness_stale_count=2,
        )
        assert any(w.code == "stale_source" for w in result.warnings)
        assert result.severity == "low"
        assert result.requires_refiner is False

    def test_all_excluded_fallback_medium_severity(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=2,
            citation_count=2,
            freshness_all_excluded_fallback=True,
        )
        stale_warnings = [w for w in result.warnings if w.code == "stale_source"]
        assert len(stale_warnings) > 0
        high_or_medium = any(w.severity_level >= 2 for w in stale_warnings)
        assert high_or_medium

    def test_ocr_low_quality_low_severity(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            ocr_low_confidence_chunk_count=2,
        )
        assert any(w.code == "ocr_low_quality" for w in result.warnings)
        assert result.severity == "low"

    def test_table_low_confidence(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            table_low_confidence_count=1,
        )
        assert any(w.code == "table_low_confidence" for w in result.warnings)

    def test_extraction_quality(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            extraction_warning_count=1,
        )
        assert any(w.code == "extraction_quality" for w in result.warnings)

    def test_max_severity_wins(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            gv_applied=True,
            gv_unsupported_count=1,  # high
            freshness_stale_count=2,  # low
            ocr_low_confidence_chunk_count=1,  # low
        )
        assert result.severity == "high"

    def test_refiner_not_triggered_below_threshold(self):
        critic_high_only = AnswerCriticService(refiner_severity_threshold="high")
        result = critic_high_only.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            gv_applied=True,
            gv_not_enough_evidence_count=2,  # medium severity
        )
        assert result.severity == "medium"
        assert result.requires_refiner is False  # threshold is "high"

    def test_error_fallback(self):
        with patch.object(
            AnswerCriticService,
            "evaluate",
            side_effect=RuntimeError("boom"),
        ):
            critic = AnswerCriticService()
        # Directly test _fallback
        fallback = AnswerCriticService._fallback()
        assert fallback.severity == "none"
        assert fallback.requires_refiner is False
        assert fallback.warnings == []

    def test_refiner_instruction_for_unsupported_claims(self):
        warnings = [
            CriticWarning(
                code="citation_unsupported", detail="2 claims unsupported", severity_level=3
            )
        ]
        instruction = _build_refiner_instruction(warnings)
        assert "Remove all claims" in instruction

    def test_refiner_instruction_for_source_conflict(self):
        warnings = [CriticWarning(code="source_conflict", detail="conflict", severity_level=3)]
        instruction = _build_refiner_instruction(warnings)
        assert "conflict" in instruction.lower()

    def test_refiner_instruction_combined(self):
        warnings = [
            CriticWarning(code="citation_unsupported", detail="x", severity_level=3),
            CriticWarning(code="stale_source", detail="y", severity_level=1),
        ]
        instruction = _build_refiner_instruction(warnings)
        assert "Remove" in instruction
        assert "outdated" in instruction

    def test_latency_ms_non_negative(self):
        result = self.critic.evaluate(not_found=False, selected_chunk_count=3, citation_count=2)
        assert result.latency_ms >= 0


# ===========================================================================
# AnswerRefinerService
# ===========================================================================


class _MockResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class TestAnswerRefinerService:
    def setup_method(self):
        self.refiner = AnswerRefinerService()

    def _mock_provider(self, json_content: str):
        mock = MagicMock()
        mock.complete = AsyncMock(return_value=_MockResponse(json_content))
        return mock

    @pytest.mark.asyncio
    async def test_refines_answer(self):
        json_resp = '{"refined_answer": "Supported claim only.", "changes_made": ["Removed unsupported claim about X"], "unsupported_claims_removed": 1}'
        with patch.object(
            self.refiner, "_resolve_provider", return_value=self._mock_provider(json_resp)
        ):
            result = await self.refiner.refine(
                draft_answer="Supported claim only. Plus unsupported claim.",
                critic_instruction="Remove unsupported claims.",
                citation_snippets=["Source says supported claim only."],
            )
        assert result.applied is True
        assert result.draft_changed is True
        assert "Supported claim" in result.refined_answer
        assert result.unsupported_claims_removed == 1

    @pytest.mark.asyncio
    async def test_no_change_when_answer_matches_draft(self):
        original = "The answer is 42."
        json_resp = f'{{"refined_answer": "{original}", "changes_made": [], "unsupported_claims_removed": 0}}'
        with patch.object(
            self.refiner, "_resolve_provider", return_value=self._mock_provider(json_resp)
        ):
            result = await self.refiner.refine(
                draft_answer=original,
                critic_instruction="No changes needed.",
                citation_snippets=["Evidence."],
            )
        assert result.applied is True
        assert result.draft_changed is False

    @pytest.mark.asyncio
    async def test_empty_refined_answer_signals_not_found(self):
        json_resp = '{"refined_answer": "", "changes_made": ["All claims removed"], "unsupported_claims_removed": 3}'
        with patch.object(
            self.refiner, "_resolve_provider", return_value=self._mock_provider(json_resp)
        ):
            result = await self.refiner.refine(
                draft_answer="Completely unsupported answer.",
                critic_instruction="Remove all claims.",
                citation_snippets=[],
            )
        assert result.applied is True
        assert result.refined_answer == ""

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self):
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch.object(self.refiner, "_resolve_provider", return_value=provider):
            result = await self.refiner.refine(
                draft_answer="Original answer.",
                critic_instruction="Fix this.",
                citation_snippets=["Evidence."],
            )
        assert result.applied is False
        assert result.refined_answer == "Original answer."

    @pytest.mark.asyncio
    async def test_fallback_on_json_parse_error(self):
        provider = self._mock_provider("not valid json at all {")
        with patch.object(self.refiner, "_resolve_provider", return_value=provider):
            result = await self.refiner.refine(
                draft_answer="Safe answer.",
                critic_instruction="Fix.",
                citation_snippets=["X."],
            )
        assert result.applied is False
        assert result.refined_answer == "Safe answer."

    @pytest.mark.asyncio
    async def test_empty_draft_skips_refiner(self):
        result = await self.refiner.refine(
            draft_answer="",
            critic_instruction="N/A",
            citation_snippets=[],
        )
        assert result.applied is False

    @pytest.mark.asyncio
    async def test_citation_snippets_capped_at_10(self):
        captured_prompts: list[str] = []

        async def capture(request):
            captured_prompts.append(request.prompt)
            return _MockResponse(
                '{"refined_answer": "ok", "changes_made": [], "unsupported_claims_removed": 0}'
            )

        provider = MagicMock()
        provider.complete = capture
        with patch.object(self.refiner, "_resolve_provider", return_value=provider):
            await self.refiner.refine(
                draft_answer="Answer.",
                critic_instruction="Fix.",
                citation_snippets=[f"citation_{i}" for i in range(15)],
            )

        prompt = captured_prompts[0]
        assert "[CITATION 10]" in prompt
        assert "[CITATION 11]" not in prompt

    def test_build_refiner_prompt_structure(self):
        prompt = _build_refiner_prompt(
            draft_answer="The answer is yes.",
            critic_instruction="Remove claims.",
            citation_snippets=["Source A says yes."],
        )
        assert "CRITIC INSTRUCTIONS:" in prompt
        assert "DRAFT ANSWER:" in prompt
        assert "VALIDATED CITATIONS:" in prompt
        assert "[CITATION 1]" in prompt
        assert "Source A says yes." in prompt


# ===========================================================================
# Trust metadata schema
# ===========================================================================


class TestPlannerCriticRecord:
    def test_default_values(self):
        record = PlannerCriticRecord()
        assert record.strategy == "standard"
        assert record.high_risk is False
        assert record.critic_warnings == []
        assert record.critic_severity == "none"
        assert record.refiner_applied is False

    def test_with_warnings(self):
        record = PlannerCriticRecord(
            strategy="legal_compliance",
            high_risk=True,
            critic_warnings=[
                CriticWarningRecord(
                    code="source_conflict", detail="Sources conflict.", severity="high"
                )
            ],
            critic_severity="high",
            refiner_applied=True,
            draft_changed=True,
            unsupported_claims_removed=2,
        )
        assert record.strategy == "legal_compliance"
        assert record.high_risk is True
        assert len(record.critic_warnings) == 1
        assert record.critic_warnings[0].code == "source_conflict"
        assert record.critic_severity == "high"
        assert record.unsupported_claims_removed == 2

    def test_serialization(self):
        record = PlannerCriticRecord(
            strategy="comparison",
            high_risk=True,
            critic_severity="medium",
            refiner_applied=True,
            draft_changed=False,
        )
        data = record.model_dump(mode="json")
        assert data["strategy"] == "comparison"
        assert data["high_risk"] is True
        assert data["critic_severity"] == "medium"

    def test_critic_warning_record_severity_literal(self):
        # Only "low", "medium", "high" are valid
        for sev in ("low", "medium", "high"):
            w = CriticWarningRecord(code="test", detail="d", severity=sev)
            assert w.severity == sev


# ===========================================================================
# Compliance / Legal / HR / Comparison answer scenario tests
# ===========================================================================


class TestHighRiskScenarios:
    """Scenario tests validating the planner correctly flags high-risk question types."""

    def setup_method(self):
        self.planner = AnswerPlannerService()
        self.critic = AnswerCriticService()

    def test_gdpr_data_protection(self):
        result = self.planner.classify(
            question="Under GDPR what data protection measures are required?"
        )
        assert result.strategy == "legal_compliance"
        assert result.high_risk is True

    def test_hr_leave_policy(self):
        result = self.planner.classify(question="What is the parental leave policy for employees?")
        assert result.strategy == "policy_lookup"
        assert result.high_risk is True

    def test_compliance_audit(self):
        result = self.planner.classify(
            question="What are the mandatory regulatory compliance requirements?"
        )
        assert result.strategy == "legal_compliance"
        assert result.high_risk is True

    def test_comparison_two_products(self):
        result = self.planner.classify(
            question="What is the difference between product A and product B?"
        )
        assert result.strategy == "comparison"
        assert result.high_risk is True

    def test_critic_legal_answer_with_conflicts(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=4,
            citation_count=3,
            gv_applied=True,
            gv_conflicting_count=2,
            gv_unsupported_count=1,
        )
        assert result.severity == "high"
        assert result.requires_refiner is True
        codes = {w.code for w in result.warnings}
        assert "source_conflict" in codes
        assert "citation_unsupported" in codes

    def test_critic_compliance_answer_with_stale_sources(self):
        result = self.critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            freshness_stale_count=2,
        )
        # Stale sources are low severity — refiner not triggered by default
        assert result.severity == "low"
        assert result.requires_refiner is False

    def test_unsupported_claim_removal_via_refiner_instruction(self):
        critic = AnswerCriticService()
        eval_result = critic.evaluate(
            not_found=False,
            selected_chunk_count=3,
            citation_count=2,
            gv_applied=True,
            gv_unsupported_count=2,
        )
        assert eval_result.requires_refiner is True
        assert "Remove" in eval_result.refiner_instruction

    def test_no_sources_found_refiner_instruction(self):
        eval_result = self.critic.evaluate(not_found=True, selected_chunk_count=0, citation_count=0)
        assert "not found" in eval_result.refiner_instruction.lower()


# ===========================================================================
# Integration helpers: _resolve_planner_critic_controls, _build_planner_critic_record
# ===========================================================================


class TestPipelineHelpers:
    """Tests for the pipeline helper functions in chat.py."""

    def test_resolve_controls_feature_disabled(self):
        from app.interfaces.http.chat import _resolve_planner_critic_controls

        with patch("app.interfaces.http.chat.settings") as mock_settings:
            mock_settings.feature_enable_planner_critic_refiner = False
            mock_settings.planner_critic_refiner_mode = "high_risk_only"
            enabled, mode, high_risk = _resolve_planner_critic_controls(None)
        assert enabled is False

    def test_resolve_controls_rag_profile_override(self):
        from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig
        from app.interfaces.http.chat import _resolve_planner_critic_controls

        profile = RagProfileConfig(
            planner_critic_refiner_enabled=True,
            planner_critic_refiner_mode="always",
            planner_high_risk_strategies=["comparison"],
        )
        with patch("app.interfaces.http.chat.settings") as mock_settings:
            mock_settings.feature_enable_planner_critic_refiner = False
            mock_settings.planner_critic_refiner_mode = "high_risk_only"
            enabled, mode, high_risk = _resolve_planner_critic_controls(profile)
        assert enabled is True
        assert mode == "always"
        assert "comparison" in high_risk

    def test_build_planner_critic_record_none(self):
        from app.interfaces.http.chat import _build_planner_critic_record

        record = _build_planner_critic_record(
            planner_result=None, critic_result=None, refiner_result=None
        )
        assert record.strategy == "standard"
        assert record.high_risk is False
        assert record.critic_warnings == []

    def test_build_planner_critic_record_full(self):
        from app.interfaces.http.chat import _build_planner_critic_record
        from app.domains.chat.services.answer_planner_service import PlannerResult
        from app.domains.chat.services.answer_critic_service import CriticResult, CriticWarning
        from app.domains.chat.services.answer_refiner_service import RefinerResult

        planner = PlannerResult(strategy="legal_compliance", high_risk=True, latency_ms=1)
        critic = CriticResult(
            warnings=[CriticWarning(code="source_conflict", detail="conflict", severity_level=3)],
            severity="high",
            requires_refiner=True,
            refiner_instruction="Fix it.",
            latency_ms=2,
        )
        refiner = RefinerResult(
            applied=True,
            draft_changed=True,
            refined_answer="Revised.",
            changes_made=["Removed unsupported claim."],
            unsupported_claims_removed=1,
            latency_ms=50,
        )
        record = _build_planner_critic_record(
            planner_result=planner, critic_result=critic, refiner_result=refiner
        )
        assert record.strategy == "legal_compliance"
        assert record.high_risk is True
        assert len(record.critic_warnings) == 1
        assert record.critic_warnings[0].code == "source_conflict"
        assert record.critic_warnings[0].severity == "high"
        assert record.critic_severity == "high"
        assert record.refiner_applied is True
        assert record.draft_changed is True
        assert record.unsupported_claims_removed == 1
        assert record.planner_latency_ms == 1
        assert record.critic_latency_ms == 2
        assert record.refiner_latency_ms == 50
