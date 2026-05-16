from uuid import UUID

from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationJudgeScores,
    EvaluationMetricOptions,
    EvaluationMetricsService,
    RetrievedMetricChunk,
)


def test_question_metrics_compute_retrieval_precision_recall_hit_rate() -> None:
    service = EvaluationMetricsService()
    expected_document_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    other_document_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    metrics = service.score_question(
        expected_document_id=expected_document_id,
        expected_page_number=2,
        expected_answer="Leave is twenty days.",
        generated_answer="Leave is twenty days.",
        not_found=False,
        retrieved_chunks=[
            RetrievedMetricChunk(document_id=expected_document_id, page_number=2),
            RetrievedMetricChunk(document_id=other_document_id, page_number=8),
        ],
        selected_chunk_count=2,
        citation_count=1,
        citation_accuracy_score=0.9,
        latency_ms=420,
        cost_usd=0.0005,
        token_input_count=120,
        token_output_count=40,
        options=EvaluationMetricOptions(),
    )

    assert metrics.retrieval_hit_rate == 1.0
    assert metrics.context_precision == 0.5
    assert metrics.context_recall == 1.0
    assert metrics.refusal_accuracy is None
    assert metrics.citation_accuracy_score == 0.9


def test_question_metrics_refusal_accuracy_for_no_expected_answer() -> None:
    service = EvaluationMetricsService()
    metrics = service.score_question(
        expected_document_id=None,
        expected_page_number=None,
        expected_answer=None,
        generated_answer="",
        not_found=True,
        retrieved_chunks=[],
        selected_chunk_count=0,
        citation_count=0,
        citation_accuracy_score=None,
        latency_ms=33,
        cost_usd=0.0,
        token_input_count=0,
        token_output_count=0,
        options=EvaluationMetricOptions(),
    )

    assert metrics.retrieval_hit_rate is None
    assert metrics.context_precision is None
    assert metrics.context_recall is None
    assert metrics.refusal_accuracy == 1.0
    assert metrics.answer_relevance_score == 1.0
    assert metrics.faithfulness_score == 1.0


def test_question_metrics_uses_mocked_judge_scores_when_enabled() -> None:
    service = EvaluationMetricsService()
    expected_document_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    metrics = service.score_question(
        expected_document_id=expected_document_id,
        expected_page_number=1,
        expected_answer="The policy grants 20 leave days.",
        generated_answer="The policy grants 20 leave days.",
        not_found=False,
        retrieved_chunks=[RetrievedMetricChunk(document_id=expected_document_id, page_number=1)],
        selected_chunk_count=1,
        citation_count=1,
        citation_accuracy_score=1.0,
        latency_ms=52,
        cost_usd=0.0002,
        token_input_count=80,
        token_output_count=20,
        options=EvaluationMetricOptions(
            faithfulness_enabled=True,
            answer_relevance_enabled=True,
            judge_provider="llm_judge",
        ),
        judge_scores=EvaluationJudgeScores(
            faithfulness_score=0.78,
            answer_relevance_score=0.88,
            provider="llm_judge",
        ),
    )

    assert metrics.judge_used is True
    assert metrics.judge_provider == "llm_judge"
    assert metrics.faithfulness_score == 0.78
    assert metrics.answer_relevance_score == 0.88


def test_run_metrics_summary_aggregates_latency_cost_and_rates() -> None:
    service = EvaluationMetricsService()
    first = service.score_question(
        expected_document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        expected_page_number=3,
        expected_answer="A",
        generated_answer="A",
        not_found=False,
        retrieved_chunks=[RetrievedMetricChunk(document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), page_number=3)],
        selected_chunk_count=1,
        citation_count=1,
        citation_accuracy_score=1.0,
        latency_ms=100,
        cost_usd=0.0004,
        token_input_count=90,
        token_output_count=12,
        options=EvaluationMetricOptions(),
    )
    second = service.score_question(
        expected_document_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        expected_page_number=1,
        expected_answer="B",
        generated_answer="not found",
        not_found=True,
        retrieved_chunks=[],
        selected_chunk_count=0,
        citation_count=0,
        citation_accuracy_score=None,
        latency_ms=300,
        cost_usd=0.0001,
        token_input_count=30,
        token_output_count=0,
        options=EvaluationMetricOptions(),
    )

    summary = service.summarize_run(
        metrics=[first, second],
        total_questions=3,
        success_count=2,
        failure_count=1,
    )

    assert summary["question_total_count"] == 3
    assert summary["question_success_count"] == 2
    assert summary["question_failure_count"] == 1
    assert summary["latency_ms_total"] == 400
    assert summary["latency_ms_average"] == 200.0
    assert summary["cost_usd_total"] == 0.0005
    assert summary["cost_usd_average"] == 0.00025
    assert summary["retrieval_hit_rate"] == 0.5
