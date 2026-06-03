from __future__ import annotations

from collections import defaultdict
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.logging import log_evaluation_event
from app.db.session import SessionLocal
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.safety_evals.repositories.safety_evals import SafetyEvalRepository
from app.domains.safety_evals.services.safety_eval_scoring_service import (
    SafetyEvalScoringService,
)
from app.models.safety_eval import SafetyEvalCase
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

_safety_eval_repository = SafetyEvalRepository()
_scoring_service = SafetyEvalScoringService()
_audit_log_service = AuditLogService()


@dataclass(frozen=True)
class _CaseSummary:
    case_id: str
    case_name: str
    suite_name: str
    violation_type: str
    severity: str
    passed: bool
    score: float
    latency_ms: int


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


def _build_summary(
    *,
    case_summaries: list[_CaseSummary],
    total: int,
    pass_count: int,
    fail_count: int,
    baseline_pass_rate: float | None,
    regression_threshold: float | None,
    suite_name: str | None,
    model_version: str | None,
) -> dict[str, Any]:
    pass_rate = round(pass_count / total, 4) if total > 0 else None

    by_violation: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"pass": 0, "fail": 0, "total": 0, "pass_rate": None}
    )
    by_severity: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"pass": 0, "fail": 0, "total": 0, "pass_rate": None}
    )

    for cs in case_summaries:
        vt = cs.violation_type
        sv = cs.severity
        by_violation[vt]["total"] += 1
        by_severity[sv]["total"] += 1
        if cs.passed:
            by_violation[vt]["pass"] += 1
            by_severity[sv]["pass"] += 1
        else:
            by_violation[vt]["fail"] += 1
            by_severity[sv]["fail"] += 1

    for bucket in by_violation.values():
        t = bucket["total"]
        bucket["pass_rate"] = round(bucket["pass"] / t, 4) if t > 0 else None

    for bucket in by_severity.values():
        t = bucket["total"]
        bucket["pass_rate"] = round(bucket["pass"] / t, 4) if t > 0 else None

    failed_cases = [
        {
            "case_id": cs.case_id,
            "case_name": cs.case_name,
            "suite_name": cs.suite_name,
            "violation_type": cs.violation_type,
            "severity": cs.severity,
        }
        for cs in case_summaries
        if not cs.passed
    ]

    regression_detected = False
    if (
        pass_rate is not None
        and baseline_pass_rate is not None
        and regression_threshold is not None
    ):
        regression_detected = pass_rate < baseline_pass_rate - regression_threshold

    return {
        "total_cases": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "baseline_pass_rate": baseline_pass_rate,
        "regression_detected": regression_detected,
        "regression_threshold": regression_threshold,
        "suite_name": suite_name,
        "model_version": model_version,
        "by_violation_type": dict(by_violation),
        "by_severity": dict(by_severity),
        "failed_cases": failed_cases,
    }


async def _run_safety_eval_async(
    safety_eval_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    try:
        parsed_run_id = _parse_uuid(safety_eval_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid safety_eval_run_id: {safety_eval_run_id}") from exc

    org_uuid = _parse_optional_uuid(organization_id)
    if org_uuid is None:
        raise PermanentTaskError("Missing organization_id for safety eval run")

    async with SessionLocal() as session:
        run = await _safety_eval_repository.get_run_by_id(
            session,
            run_id=parsed_run_id,
            organization_id=org_uuid,
        )
        if run is None:
            raise PermanentTaskError(f"Safety eval run not found: {safety_eval_run_id}")

        raw_config = run.config if isinstance(run.config, dict) else {}
        suite_name = run.suite_name
        regression_threshold = raw_config.get("regression_threshold")
        if isinstance(regression_threshold, (int, float)):
            regression_threshold = float(max(0.0, min(1.0, regression_threshold)))
        else:
            regression_threshold = None
        model_version = raw_config.get("model_version")
        if not isinstance(model_version, str) or not model_version.strip():
            model_version = None

        cases: list[SafetyEvalCase] = await _safety_eval_repository.list_all_cases_for_run(
            session,
            organization_id=org_uuid,
            suite_name=suite_name,
        )
        if not cases:
            log_evaluation_event(
                event="safety_eval.run.no_cases",
                job_id=safety_eval_run_id,
                organization_id=organization_id,
                user_id=user_id,
                request_id=request_id,
            )

        baseline_pass_rate: float | None = None
        baseline_run = await _safety_eval_repository.get_latest_completed_run(
            session,
            organization_id=org_uuid,
            suite_name=suite_name,
            before_run_id=parsed_run_id,
        )
        if baseline_run is not None and isinstance(baseline_run.summary, dict):
            raw_bpr = baseline_run.summary.get("pass_rate")
            if isinstance(raw_bpr, (int, float)):
                baseline_pass_rate = float(raw_bpr)

        # Idempotent: clear stale results before re-running.
        try:
            await _safety_eval_repository.delete_results_for_run(session, run_id=parsed_run_id)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to clear stale results for run: {safety_eval_run_id}"
            ) from exc

    # Score every case outside the DB session to keep transactions short.
    case_summaries: list[_CaseSummary] = []
    scored_results: list[dict[str, Any]] = []

    for case in cases:
        scored = _scoring_service.score(
            violation_type=case.violation_type,
            prompt_text=case.prompt_text,
        )
        case_summaries.append(
            _CaseSummary(
                case_id=str(case.id),
                case_name=case.name,
                suite_name=case.suite_name,
                violation_type=case.violation_type,
                severity=case.severity,
                passed=scored.passed,
                score=scored.score,
                latency_ms=scored.latency_ms,
            )
        )
        scored_results.append(
            {
                "case": case,
                "scored": scored,
            }
        )

        log_evaluation_event(
            event="safety_eval.case.scored",
            job_id=safety_eval_run_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            case_id=str(case.id),
            violation_type=case.violation_type,
            passed=scored.passed,
        )

    total = len(cases)
    pass_count = sum(1 for cs in case_summaries if cs.passed)
    fail_count = total - pass_count

    summary = _build_summary(
        case_summaries=case_summaries,
        total=total,
        pass_count=pass_count,
        fail_count=fail_count,
        baseline_pass_rate=baseline_pass_rate,
        regression_threshold=regression_threshold,
        suite_name=suite_name,
        model_version=model_version,
    )

    # Persist results and final run state.
    async with SessionLocal() as session:
        for item in scored_results:
            scored_case: SafetyEvalCase = item["case"]
            scored = item["scored"]
            try:
                await _safety_eval_repository.create_result(
                    session,
                    safety_eval_run_id=parsed_run_id,
                    safety_eval_case_id=scored_case.id,
                    passed=scored.passed,
                    violation_detected=scored.violation_detected,
                    violation_type=scored.violation_type,
                    score=scored.score,
                    latency_ms=scored.latency_ms,
                    details={
                        **scored.details,
                        "case_name": scored_case.name,
                        "case_suite": scored_case.suite_name,
                        "case_severity": scored_case.severity,
                        "prompt_text_preview": scored_case.prompt_text[:200],
                    },
                )
            except Exception as exc:
                await session.rollback()
                raise TransientTaskError(
                    f"Unable to persist safety eval result for case {scored_case.id}"
                ) from exc

        try:
            await _safety_eval_repository.update_run_status(
                session,
                run_id=parsed_run_id,
                status="completed",
                mark_completed=True,
                pass_count=pass_count,
                fail_count=fail_count,
                total_count=total,
                summary=summary,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to finalize safety eval run: {safety_eval_run_id}"
            ) from exc

    return {
        "safety_eval_run_id": safety_eval_run_id,
        "total_cases": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "all_passed": total > 0 and pass_count == total,
        "summary": summary,
    }


class SafetyEvalTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        run_id = kwargs.get("safety_eval_run_id")
        if run_id is None and args:
            run_id = args[0]
        if not isinstance(run_id, str):
            return
        try:
            org_id = _parse_optional_uuid(kwargs.get("organization_id"))
            if org_id is None:
                return

            async def _mark_failed() -> None:
                async with SessionLocal() as session:
                    await _safety_eval_repository.update_run_status(
                        session,
                        run_id=_parse_uuid(run_id),
                        status="failed",
                        mark_completed=True,
                    )
                    await session.commit()

            _run(_mark_failed())
            log_evaluation_event(
                event="safety_eval.run.failed",
                job_id=run_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                error=str(exc),
            )
        except Exception:
            return


@celery_app.task(
    name="safety_evals.run",
    bind=True,
    base=SafetyEvalTask,
    ignore_result=True,
)
def run_safety_eval(
    self: SafetyEvalTask,
    safety_eval_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Score all safety eval cases for a run and persist results."""
    log_evaluation_event(
        event="safety_eval.run.started",
        job_id=safety_eval_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
    )

    try:
        org_uuid = _parse_optional_uuid(organization_id)
        if org_uuid is None:
            raise PermanentTaskError("Missing organization_id")

        async def _mark_running() -> None:
            async with SessionLocal() as session:
                await _safety_eval_repository.update_run_status(
                    session,
                    run_id=_parse_uuid(safety_eval_run_id),
                    status="running",
                    mark_started=True,
                )
                await session.commit()

        _run(_mark_running())
    except PermanentTaskError:
        raise
    except Exception as exc:
        raise TransientTaskError(
            f"Unable to mark safety eval run as running: {safety_eval_run_id}"
        ) from exc

    result: dict[str, Any] = _run(
        _run_safety_eval_async(
            safety_eval_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    log_evaluation_event(
        event="safety_eval.run.completed",
        job_id=safety_eval_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        total_cases=result["total_cases"],
        pass_count=result["pass_count"],
        fail_count=result["fail_count"],
    )
    return result
