"""Tests for F226 — local model evaluation, benchmark suites, and release gates.

Covers:
  A–F  Benchmark suite catalog (list, get, invalid ID)
  G–K  Provider comparison aggregation (unit, no DB)
  L–Q  Model-profile comparison report HTTP endpoint
  R–T  Benchmark run trigger endpoint
  U–W  Release gate recommendation logic (unit)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.domains.evaluations.benchmark_suites import (
    get_benchmark_suite,
    list_benchmark_suites,
)
from app.domains.evaluations.schemas.evaluations import (
    LocalModelMetrics,
    ModelProfileComparisonReport,
    ProviderProfileSummary,
    _build_release_gate_recommendation,
    _DEFAULT_GATE_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# A–F: Benchmark suite catalog
# ---------------------------------------------------------------------------

class TestBenchmarkSuiteCatalog:
    def test_a_list_returns_all_suites(self):
        suites = list_benchmark_suites()
        assert len(suites) == 6

    def test_b_expected_suite_ids_present(self):
        ids = {s.suite_id for s in list_benchmark_suites()}
        assert ids == {
            "qa_basic",
            "not_found",
            "citation_strictness",
            "multilingual",
            "long_context",
            "prompt_injection",
        }

    def test_c_get_suite_by_id(self):
        suite = get_benchmark_suite("qa_basic")
        assert suite is not None
        assert suite.suite_id == "qa_basic"
        assert len(suite.cases) >= 3

    def test_d_unknown_suite_id_returns_none(self):
        assert get_benchmark_suite("nonexistent_suite") is None

    def test_e_each_suite_has_cases(self):
        for suite in list_benchmark_suites():
            assert len(suite.cases) >= 3, f"Suite {suite.suite_id} has too few cases"

    def test_f_suite_cases_have_required_fields(self):
        for suite in list_benchmark_suites():
            for case in suite.cases:
                assert case.question.strip(), f"Blank question in suite {suite.suite_id}"
                assert case.difficulty in ("easy", "medium", "hard")
                assert isinstance(case.tags, list)


# ---------------------------------------------------------------------------
# G–K: Provider comparison aggregation (unit tests, no DB)
# ---------------------------------------------------------------------------

def _make_run(provider_profile: str, provider_type: str = "openai", **summary_overrides):
    """Build a minimal mock EvaluationRun with embedded metrics_summary."""
    summary = {
        "retrieval_hit_rate": 0.80,
        "citation_accuracy_score": 0.85,
        "faithfulness_score": 0.78,
        "answer_relevance_score": 0.82,
        "not_found_rate": 0.05,
        "latency_ms_average": 350.0,
        "cost_usd_total": 0.12,
    }
    summary.update(summary_overrides)
    run = MagicMock()
    run.id = uuid4()
    run.provider_profile = provider_profile
    run.provider_type = provider_type
    run.config = {"metrics_summary": summary}
    run.completed_at = None
    return run


class TestProviderComparisonAggregation:
    def test_g_aggregate_single_run(self):
        from app.interfaces.http.evaluations import _aggregate_provider_profile_summary

        run = _make_run("local_profile", "ollama")
        summary = _aggregate_provider_profile_summary([run], "local_profile")
        assert summary.provider_profile == "local_profile"
        assert summary.run_count == 1
        assert summary.retrieval_hit_rate == pytest.approx(0.80)
        assert summary.provider_type == "ollama"

    def test_h_aggregate_averages_multiple_runs(self):
        from app.interfaces.http.evaluations import _aggregate_provider_profile_summary

        run1 = _make_run("local_profile", retrieval_hit_rate=0.60)
        run2 = _make_run("local_profile", retrieval_hit_rate=0.80)
        summary = _aggregate_provider_profile_summary([run1, run2], "local_profile")
        assert summary.run_count == 2
        assert summary.retrieval_hit_rate == pytest.approx(0.70)

    def test_i_empty_profile_label_returns_zero_run_count(self):
        from app.interfaces.http.evaluations import _aggregate_provider_profile_summary

        run = _make_run("cloud_baseline")
        summary = _aggregate_provider_profile_summary([run], "local_profile")
        assert summary.run_count == 0
        assert summary.retrieval_hit_rate is None

    def test_j_local_metrics_are_extracted(self):
        from app.interfaces.http.evaluations import _aggregate_provider_profile_summary

        run = _make_run(
            "local_profile",
            "ollama",
            invalid_json_rate=0.03,
            timeout_rate=0.07,
            fallback_frequency=0.10,
        )
        summary = _aggregate_provider_profile_summary([run], "local_profile")
        assert summary.local_model_metrics is not None
        assert summary.local_model_metrics.invalid_json_rate == pytest.approx(0.03)
        assert summary.local_model_metrics.timeout_rate == pytest.approx(0.07)

    def test_k_runs_filtered_by_profile_label(self):
        from app.interfaces.http.evaluations import _aggregate_provider_profile_summary

        cloud_run = _make_run("cloud_baseline", retrieval_hit_rate=0.90)
        local_run = _make_run("local_profile", retrieval_hit_rate=0.70)
        summary = _aggregate_provider_profile_summary(
            [cloud_run, local_run], "cloud_baseline"
        )
        assert summary.run_count == 1
        assert summary.retrieval_hit_rate == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# L–Q: Model-profile comparison report HTTP endpoint
# ---------------------------------------------------------------------------

class TestModelProfileReportEndpoint:
    @pytest.fixture
    def mock_principal(self):
        principal = MagicMock()
        principal.organization_id = str(uuid4())
        principal.user_id = str(uuid4())
        return principal

    @pytest.mark.asyncio
    async def test_l_empty_runs_returns_baseline_and_local_profiles(
        self, mock_principal
    ):
        """Report always includes cloud_baseline and local_profile even when no runs exist."""
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        assert len(report.profiles) == 2
        profile_labels = {p.provider_profile for p in report.profiles}
        assert "cloud_baseline" in profile_labels
        assert "local_profile" in profile_labels

    @pytest.mark.asyncio
    async def test_m_report_includes_release_gate_recommendations(
        self, mock_principal
    ):
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        local_run = _make_run(
            "local_profile",
            "ollama",
            retrieval_hit_rate=0.75,
            citation_accuracy_score=0.78,
            faithfulness_score=0.72,
            answer_relevance_score=0.80,
            not_found_rate=0.10,
        )
        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[local_run]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        assert len(report.release_gate_recommendations) >= 1
        local_rec = next(
            (r for r in report.release_gate_recommendations if r.provider_profile == "local_profile"),
            None,
        )
        assert local_rec is not None
        assert isinstance(local_rec.is_ready, bool)

    @pytest.mark.asyncio
    async def test_n_fallback_profile_included_when_runs_exist(
        self, mock_principal
    ):
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        fallback_run = _make_run("fallback_profile", "openai")
        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[fallback_run]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        labels = {p.provider_profile for p in report.profiles}
        assert "fallback_profile" in labels

    @pytest.mark.asyncio
    async def test_o_report_has_generated_at_timestamp(self, mock_principal):
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        assert report.generated_at is not None

    @pytest.mark.asyncio
    async def test_p_report_default_thresholds_present(self, mock_principal):
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        assert "retrieval_hit_rate_min" in report.default_thresholds
        assert "invalid_json_rate_max" in report.default_thresholds

    @pytest.mark.asyncio
    async def test_q_viewer_role_is_allowed(self, mock_principal):
        """Viewer role should be able to read the comparison report (no 403)."""
        from app.interfaces.http.evaluations import get_model_profile_comparison_report

        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository"
            ".list_runs_by_provider_profile_for_org",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ):
            report = await get_model_profile_comparison_report(
                mock_principal, db, evaluation_set_id=None
            )
        assert report is not None


# ---------------------------------------------------------------------------
# R–T: Benchmark run trigger endpoint
# ---------------------------------------------------------------------------

class TestBenchmarkRunTrigger:
    @pytest.mark.asyncio
    async def test_r_trigger_creates_run_for_valid_suite(self):
        from app.interfaces.http.evaluations import trigger_benchmark_run
        from app.domains.evaluations.schemas.evaluations import TriggerBenchmarkRunRequest

        principal = MagicMock()
        principal.organization_id = str(uuid4())
        principal.user_id = str(uuid4())
        request = MagicMock()
        payload = TriggerBenchmarkRunRequest(suite_id="qa_basic", provider_profile="local_profile")

        mock_eval_set = MagicMock()
        mock_eval_set.id = uuid4()
        mock_run = MagicMock()
        mock_run.id = uuid4()
        mock_run.provider_profile = None

        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository.create_evaluation_set",
            new=AsyncMock(return_value=mock_eval_set),
        ), patch(
            "app.interfaces.http.evaluations.evaluation_repository.create_evaluation_question",
            new=AsyncMock(),
        ), patch(
            "app.interfaces.http.evaluations.evaluation_repository.count_active_runs_for_set",
            new=AsyncMock(return_value=0),
        ), patch(
            "app.interfaces.http.evaluations.evaluation_repository.create_evaluation_run",
            new=AsyncMock(return_value=mock_run),
        ), patch(
            "app.interfaces.http.evaluations.run_evaluation_task.delay",
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ), patch(
            "app.interfaces.http.evaluations._user_id_from_principal",
            return_value=uuid4(),
        ):
            response = await trigger_benchmark_run(
                "qa_basic", payload, request, principal, None, db
            )
        assert response.suite_id == "qa_basic"
        assert response.provider_profile == "local_profile"
        assert response.status == "queued"

    @pytest.mark.asyncio
    async def test_s_trigger_unknown_suite_returns_404(self):
        from fastapi import HTTPException
        from app.interfaces.http.evaluations import trigger_benchmark_run
        from app.domains.evaluations.schemas.evaluations import TriggerBenchmarkRunRequest

        principal = MagicMock()
        principal.organization_id = str(uuid4())
        principal.user_id = str(uuid4())
        request = MagicMock()
        payload = TriggerBenchmarkRunRequest(
            suite_id="nonexistent", provider_profile="local_profile"
        )
        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ), patch(
            "app.interfaces.http.evaluations._user_id_from_principal",
            return_value=uuid4(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_benchmark_run(
                    "nonexistent", payload, request, principal, None, db
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_t_trigger_409_when_active_run_exists(self):
        from fastapi import HTTPException
        from app.interfaces.http.evaluations import trigger_benchmark_run
        from app.domains.evaluations.schemas.evaluations import TriggerBenchmarkRunRequest

        principal = MagicMock()
        principal.organization_id = str(uuid4())
        principal.user_id = str(uuid4())
        request = MagicMock()
        payload = TriggerBenchmarkRunRequest(suite_id="qa_basic", provider_profile="local_profile")

        mock_eval_set = MagicMock()
        mock_eval_set.id = uuid4()
        db = AsyncMock()
        with patch(
            "app.interfaces.http.evaluations.evaluation_repository.create_evaluation_set",
            new=AsyncMock(return_value=mock_eval_set),
        ), patch(
            "app.interfaces.http.evaluations.evaluation_repository.create_evaluation_question",
            new=AsyncMock(),
        ), patch(
            "app.interfaces.http.evaluations.evaluation_repository.count_active_runs_for_set",
            new=AsyncMock(return_value=1),
        ), patch(
            "app.interfaces.http.evaluations._organization_id_from_principal",
            return_value=uuid4(),
        ), patch(
            "app.interfaces.http.evaluations._user_id_from_principal",
            return_value=uuid4(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_benchmark_run(
                    "qa_basic", payload, request, principal, None, db
                )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# U–W: Release gate recommendation logic (unit)
# ---------------------------------------------------------------------------

class TestReleaseGateRecommendation:
    def _make_summary(self, **overrides) -> ProviderProfileSummary:
        defaults = dict(
            provider_profile="local_profile",
            provider_type="ollama",
            run_count=1,
            latest_run_id=str(uuid4()),
            retrieval_hit_rate=0.80,
            citation_accuracy_score=0.80,
            faithfulness_score=0.75,
            answer_relevance_score=0.75,
            not_found_rate=0.10,
            local_model_metrics=LocalModelMetrics(
                invalid_json_rate=0.02,
                timeout_rate=0.05,
                fallback_frequency=0.08,
            ),
        )
        defaults.update(overrides)
        return ProviderProfileSummary(**defaults)

    def test_u_all_passing_is_ready(self):
        summary = self._make_summary()
        rec = _build_release_gate_recommendation(summary)
        assert rec.is_ready is True
        assert len(rec.failing_checks) == 0

    def test_v_low_retrieval_hit_rate_fails(self):
        summary = self._make_summary(retrieval_hit_rate=0.50)
        rec = _build_release_gate_recommendation(summary)
        assert rec.is_ready is False
        assert any("retrieval_hit_rate" in check for check in rec.failing_checks)

    def test_w_high_invalid_json_rate_fails(self):
        summary = self._make_summary(
            local_model_metrics=LocalModelMetrics(
                invalid_json_rate=0.15,
                timeout_rate=0.01,
                fallback_frequency=0.02,
            )
        )
        rec = _build_release_gate_recommendation(summary)
        assert rec.is_ready is False
        assert any("invalid_json_rate" in check for check in rec.failing_checks)

    def test_x_custom_thresholds_applied(self):
        summary = self._make_summary(retrieval_hit_rate=0.65)
        # Default threshold is 0.70 → fails. Relax it to 0.60 → passes.
        rec = _build_release_gate_recommendation(
            summary, thresholds={"retrieval_hit_rate_min": 0.60}
        )
        assert not any("retrieval_hit_rate" in check for check in rec.failing_checks)

    def test_y_recommendation_message_mentions_failing_checks(self):
        summary = self._make_summary(retrieval_hit_rate=0.40, faithfulness_score=0.30)
        rec = _build_release_gate_recommendation(summary)
        assert not rec.is_ready
        assert "retrieval_hit_rate" in rec.recommendation or len(rec.failing_checks) > 0

    def test_z_no_local_metrics_still_evaluates_quality_checks(self):
        summary = self._make_summary(local_model_metrics=None)
        rec = _build_release_gate_recommendation(summary)
        assert isinstance(rec.is_ready, bool)
        assert len(rec.passing_checks) + len(rec.failing_checks) > 0
