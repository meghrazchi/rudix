"""Tests for F234 — Multilingual evaluation datasets and regression gates.

Covers:
  A–D   Language heuristic detection (unit)
  E–G   Language adherence scoring (unit)
  H–J   EvaluationQuestion language fields in schema layer (unit)
  K–M   Benchmark suite multilingual cases (unit)
  N–P   Quality gate language_adherence_score_min threshold (unit)
  Q–T   Language coverage endpoint (HTTP mock)
  U–X   Language breakdown endpoint (HTTP mock)
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.domains.evaluations.benchmark_suites import get_benchmark_suite
from app.domains.evaluations.schemas.evaluations import (
    _MIN_COVERAGE_WARNING_THRESHOLD,
    CreateEvaluationQuestionRequest,
    UpdateEvaluationQuestionRequest,
)
from app.domains.evaluations.services.evaluation_metrics_service import (
    detect_language_heuristic,
    score_language_adherence,
)
from app.domains.quality_gates.schemas.quality_gates import QualityGateThresholds
from app.domains.quality_gates.services.quality_gate_service import evaluate_gate

# ---------------------------------------------------------------------------
# A–D: Language heuristic detection
# ---------------------------------------------------------------------------


class TestDetectLanguageHeuristic:
    def test_a_english_ascii_dominant(self):
        text = "This is a clear English sentence about software engineering and best practices."
        assert detect_language_heuristic(text) == "en"

    def test_b_german_umlauts(self):
        text = "Welche Hauptpunkte enthält das Compliance-Dokument zur Datenschutzgrundverordnung?"
        assert detect_language_heuristic(text) == "de"

    def test_c_spanish_special_chars(self):
        text = (
            "¿Cuáles son los requisitos de seguridad descritos en la especificación del producto?"
        )
        assert detect_language_heuristic(text) == "es"

    def test_d_short_text_returns_none(self):
        assert detect_language_heuristic("Hi") is None

    def test_d2_french_accents(self):
        text = "Résumez les points clés du document de conformité rédigé en français."
        assert detect_language_heuristic(text) == "fr"


# ---------------------------------------------------------------------------
# E–G: Language adherence scoring
# ---------------------------------------------------------------------------


class TestScoreLanguageAdherence:
    def test_e_matching_language_returns_1(self):
        answer = "This is a clear English software engineering answer with enough words."
        detected, score = score_language_adherence(answer, "en")
        assert detected == "en"
        assert score == 1.0

    def test_f_mismatching_language_returns_0(self):
        answer = "Welche Hauptpunkte enthält das Compliance-Dokument zur Datenschutz DSGVO?"
        detected, score = score_language_adherence(answer, "en")
        assert detected == "de"
        assert score == 0.0

    def test_g_no_expected_language_returns_none(self):
        answer = "Some answer text here for testing purposes and coverage."
        detected, score = score_language_adherence(answer, None)
        assert detected is None
        assert score is None

    def test_g2_none_answer_returns_none(self):
        detected, score = score_language_adherence(None, "en")
        assert detected is None
        assert score is None


# ---------------------------------------------------------------------------
# H–J: Schema layer — language fields on EvaluationQuestion
# ---------------------------------------------------------------------------


class TestEvaluationQuestionLanguageSchema:
    def test_h_create_request_accepts_language_fields(self):
        req = CreateEvaluationQuestionRequest(
            question="Was besagt die Haftungsklausel?",
            question_language="de",
            expected_answer_language="de",
            source_language="de",
            translation_notes="Cross-check against English original.",
        )
        assert req.question_language == "de"
        assert req.expected_answer_language == "de"
        assert req.source_language == "de"
        assert req.translation_notes == "Cross-check against English original."

    def test_i_create_request_language_optional(self):
        req = CreateEvaluationQuestionRequest(question="Simple question?")
        assert req.question_language is None
        assert req.expected_answer_language is None

    def test_j_update_request_accepts_language_fields(self):
        req = UpdateEvaluationQuestionRequest(
            question_language="fr",
            expected_answer_language="fr",
        )
        assert req.question_language == "fr"
        assert req.expected_answer_language == "fr"

    def test_j2_invalid_language_code_rejected(self):
        with pytest.raises(ValueError):
            CreateEvaluationQuestionRequest(
                question="Test question here?",
                question_language="zz",  # unsupported code
            )


# ---------------------------------------------------------------------------
# K–M: Benchmark suite multilingual cases
# ---------------------------------------------------------------------------


class TestMultilingualBenchmarkSuite:
    def setup_method(self):
        self.suite = get_benchmark_suite("multilingual")
        assert self.suite is not None

    def test_k_suite_has_enough_cases(self):
        assert len(self.suite.cases) >= 8

    def test_l_covers_all_four_languages(self):
        langs = {c.question_language for c in self.suite.cases if c.question_language}
        assert "en" in langs
        assert "de" in langs
        assert "es" in langs
        assert "fr" in langs

    def test_m_cross_language_case_present(self):
        cross = [
            c
            for c in self.suite.cases
            if c.question_language
            and c.source_language
            and c.question_language != c.source_language
        ]
        assert len(cross) >= 1, "Expected at least one cross-language case"

    def test_m2_all_cases_have_expected_answer_language_or_none(self):
        for case in self.suite.cases:
            if case.question_language:
                assert case.expected_answer_language in (None, "en", "de", "es", "fr")


# ---------------------------------------------------------------------------
# N–P: Quality gate language adherence threshold
# ---------------------------------------------------------------------------


class TestQualityGateLanguageAdherence:
    def test_n_threshold_accepted_in_schema(self):
        thresholds = QualityGateThresholds(language_adherence_score_min=0.80)
        assert thresholds.language_adherence_score_min == 0.80

    def test_o_gate_passes_when_metric_meets_threshold(self):
        thresholds = QualityGateThresholds(language_adherence_score_min=0.80)
        eval_summary = {"language_adherence_score": 0.90}
        verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)
        assert verdict == "passed"
        assert any(c.metric == "language_adherence_score_min" for c in passed)
        assert not any(c.metric == "language_adherence_score_min" for c in failed)

    def test_p_gate_fails_when_metric_below_threshold(self):
        thresholds = QualityGateThresholds(language_adherence_score_min=0.80)
        eval_summary = {"language_adherence_score": 0.60}
        verdict, _passed, failed = evaluate_gate(thresholds, eval_summary, None)
        assert verdict == "failed"
        assert any(c.metric == "language_adherence_score_min" for c in failed)

    def test_p2_gate_ignores_threshold_when_not_set(self):
        thresholds = QualityGateThresholds()
        eval_summary = {"language_adherence_score": 0.10}
        verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)
        assert verdict == "passed"
        assert not any(c.metric == "language_adherence_score_min" for c in passed + failed)


# ---------------------------------------------------------------------------
# Q–T: Language coverage endpoint (HTTP mock)
# ---------------------------------------------------------------------------


class TestLanguageCoverageEndpoint:
    @pytest.fixture
    def _principal(self):
        p = MagicMock()
        p.organization_id = str(uuid4())
        p.user_id = str(uuid4())
        return p

    @pytest.fixture
    def _org_id(self, _principal):
        from uuid import UUID

        return UUID(_principal.organization_id)

    @pytest.mark.asyncio
    async def test_q_returns_coverage_per_language(self, _principal, _org_id):
        from app.interfaces.http.evaluation_sets import get_language_coverage

        set_id = str(uuid4())
        eval_set = MagicMock()
        eval_set.id = uuid4()

        rows = [
            {"language": "en", "question_count": 10, "has_expected_answer_count": 8},
            {"language": "de", "question_count": 3, "has_expected_answer_count": 2},
            {"language": None, "question_count": 5, "has_expected_answer_count": 0},
        ]

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_set.return_value = eval_set
        mock_repo.get_language_coverage_for_set.return_value = rows

        import app.interfaces.http.evaluation_sets as sets_module

        original_repo = sets_module.evaluation_repository

        try:
            sets_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._get_evaluation_set_or_404",
                    return_value=eval_set,
                ),
            ):
                db = AsyncMock()
                result = await get_language_coverage(
                    evaluation_set_id=set_id,
                    principal=_principal,
                    db_session=db,
                )
        finally:
            sets_module.evaluation_repository = original_repo

        assert result.evaluation_set_id == str(eval_set.id)
        assert len(result.items) == 2
        assert result.unlabelled_count == 5
        assert result.total_question_count == 18

    @pytest.mark.asyncio
    async def test_r_flags_low_coverage_languages(self, _principal, _org_id):
        from app.interfaces.http.evaluation_sets import get_language_coverage

        eval_set = MagicMock()
        eval_set.id = uuid4()

        rows = [
            {"language": "fr", "question_count": 2, "has_expected_answer_count": 1},
            {"language": "en", "question_count": 10, "has_expected_answer_count": 9},
        ]

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_set.return_value = eval_set
        mock_repo.get_language_coverage_for_set.return_value = rows

        import app.interfaces.http.evaluation_sets as sets_module

        original_repo = sets_module.evaluation_repository

        try:
            sets_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._get_evaluation_set_or_404",
                    return_value=eval_set,
                ),
            ):
                db = AsyncMock()
                result = await get_language_coverage(
                    evaluation_set_id=str(uuid4()),
                    principal=_principal,
                    db_session=db,
                )
        finally:
            sets_module.evaluation_repository = original_repo

        assert "fr" in result.coverage_warning_languages
        assert "en" not in result.coverage_warning_languages
        fr_item = next(i for i in result.items if i.language == "fr")
        assert fr_item.has_insufficient_coverage is True

    @pytest.mark.asyncio
    async def test_s_empty_set_returns_zero_items(self, _principal, _org_id):
        from app.interfaces.http.evaluation_sets import get_language_coverage

        eval_set = MagicMock()
        eval_set.id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_set.return_value = eval_set
        mock_repo.get_language_coverage_for_set.return_value = []

        import app.interfaces.http.evaluation_sets as sets_module

        original_repo = sets_module.evaluation_repository

        try:
            sets_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluation_sets._get_evaluation_set_or_404",
                    return_value=eval_set,
                ),
            ):
                db = AsyncMock()
                result = await get_language_coverage(
                    evaluation_set_id=str(uuid4()),
                    principal=_principal,
                    db_session=db,
                )
        finally:
            sets_module.evaluation_repository = original_repo

        assert result.items == []
        assert result.total_question_count == 0

    @pytest.mark.asyncio
    async def test_t_min_coverage_threshold_is_five(self):
        assert _MIN_COVERAGE_WARNING_THRESHOLD == 5


# ---------------------------------------------------------------------------
# U–X: Language breakdown endpoint (HTTP mock)
# ---------------------------------------------------------------------------


class TestLanguageBreakdownEndpoint:
    @pytest.fixture
    def _principal(self):
        p = MagicMock()
        p.organization_id = str(uuid4())
        p.user_id = str(uuid4())
        return p

    @pytest.fixture
    def _org_id(self, _principal):
        from uuid import UUID

        return UUID(_principal.organization_id)

    def _make_result(
        self,
        *,
        question_language,
        expected_answer_language=None,
        retrieval=0.9,
        faithfulness=0.85,
        answer_relevance=0.80,
        latency_ms=120,
        not_found=False,
        generated_answer=None,
    ):
        result = MagicMock()
        result.retrieval_score = retrieval
        result.citation_accuracy_score = 0.88
        result.faithfulness_score = faithfulness
        result.answer_relevance_score = answer_relevance
        result.latency_ms = latency_ms
        result.language_match_score = None
        result.detected_answer_language = None
        result.generated_answer = generated_answer or (
            "This is a clear English answer with enough words for detection."
        )
        result.details = {"not_found": not_found, "cost_usd": 0.001}
        question = MagicMock()
        question.question_language = question_language
        question.expected_answer_language = expected_answer_language
        return result, question

    @pytest.mark.asyncio
    async def test_u_groups_results_by_language(self, _principal, _org_id):
        from app.interfaces.http.evaluations import get_language_breakdown

        run_id = str(uuid4())
        run = MagicMock()
        run.id = uuid4()

        pairs = [
            self._make_result(question_language="en"),
            self._make_result(question_language="en"),
            self._make_result(
                question_language="de",
                generated_answer="Welche Punkte enthält das Compliance-Dokument?",
            ),
        ]

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_run_for_organization.return_value = run
        mock_repo.get_results_with_questions_for_run.return_value = pairs

        import app.interfaces.http.evaluations as eval_module

        original_repo = eval_module.evaluation_repository

        try:
            eval_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._parse_evaluation_run_id",
                    return_value=run.id,
                ),
            ):
                db = AsyncMock()
                result = await get_language_breakdown(
                    evaluation_run_id=run_id,
                    principal=_principal,
                    db_session=db,
                )
        finally:
            eval_module.evaluation_repository = original_repo

        langs = {item.language for item in result.items}
        assert "en" in langs
        assert "de" in langs
        en_item = next(i for i in result.items if i.language == "en")
        assert en_item.question_count == 2

    @pytest.mark.asyncio
    async def test_v_no_language_questions_become_unlabelled(self, _principal, _org_id):
        from app.interfaces.http.evaluations import get_language_breakdown

        run = MagicMock()
        run.id = uuid4()
        pairs = [
            self._make_result(question_language=None),
            self._make_result(question_language=None),
        ]

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_run_for_organization.return_value = run
        mock_repo.get_results_with_questions_for_run.return_value = pairs

        import app.interfaces.http.evaluations as eval_module

        original_repo = eval_module.evaluation_repository

        try:
            eval_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._parse_evaluation_run_id",
                    return_value=run.id,
                ),
            ):
                db = AsyncMock()
                result = await get_language_breakdown(
                    evaluation_run_id=str(uuid4()),
                    principal=_principal,
                    db_session=db,
                )
        finally:
            eval_module.evaluation_repository = original_repo

        unlabelled = next((i for i in result.items if i.language == "unlabelled"), None)
        assert unlabelled is not None
        assert unlabelled.question_count == 2
        assert result.coverage_warning_languages == []

    @pytest.mark.asyncio
    async def test_w_computes_language_adherence_from_generated_answer(self, _principal, _org_id):
        from app.interfaces.http.evaluations import get_language_breakdown

        run = MagicMock()
        run.id = uuid4()
        result_obj, question_obj = self._make_result(
            question_language="en",
            expected_answer_language="en",
            generated_answer="This is a clear English answer text that should be detected correctly.",
        )
        pairs = [(result_obj, question_obj)]

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_run_for_organization.return_value = run
        mock_repo.get_results_with_questions_for_run.return_value = pairs

        import app.interfaces.http.evaluations as eval_module

        original_repo = eval_module.evaluation_repository

        try:
            eval_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._parse_evaluation_run_id",
                    return_value=run.id,
                ),
            ):
                db = AsyncMock()
                result = await get_language_breakdown(
                    evaluation_run_id=str(uuid4()),
                    principal=_principal,
                    db_session=db,
                )
        finally:
            eval_module.evaluation_repository = original_repo

        en_item = next(i for i in result.items if i.language == "en")
        assert en_item.language_adherence_score is not None
        assert en_item.language_adherence_score >= 0.0

    @pytest.mark.asyncio
    async def test_x_flags_low_coverage_languages(self, _principal, _org_id):
        from app.interfaces.http.evaluations import get_language_breakdown

        run = MagicMock()
        run.id = uuid4()
        pairs = [self._make_result(question_language="es")]  # only 1 question

        mock_repo = AsyncMock()
        mock_repo.get_evaluation_run_for_organization.return_value = run
        mock_repo.get_results_with_questions_for_run.return_value = pairs

        import app.interfaces.http.evaluations as eval_module

        original_repo = eval_module.evaluation_repository

        try:
            eval_module.evaluation_repository = mock_repo
            with (
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._organization_id_from_principal",
                    return_value=_org_id,
                ),
                __import__("unittest.mock", fromlist=["patch"]).patch(
                    "app.interfaces.http.evaluations._parse_evaluation_run_id",
                    return_value=run.id,
                ),
            ):
                db = AsyncMock()
                result = await get_language_breakdown(
                    evaluation_run_id=str(uuid4()),
                    principal=_principal,
                    db_session=db,
                )
        finally:
            eval_module.evaluation_repository = original_repo

        assert "es" in result.coverage_warning_languages
        es_item = next(i for i in result.items if i.language == "es")
        assert es_item.has_insufficient_coverage is True
