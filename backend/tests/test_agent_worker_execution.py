"""Agent runs executed by workers: lease, resume, idempotency, principal, reaper (R06-13).

Celery runs eagerly (``agent_worker_support``). Inline mode is covered unchanged by
``test_agent_runtime.py`` and ``test_agent_runs_api.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from agent_worker_support import (
    DOCUMENT_ID,
    AgentWorkerEnv,
    WorkerKilled,
    agent_env,  # noqa: F401  (fixture)
    build_runtime,
)
from sqlalchemy import update

from app.application.agents import run_reaper, run_submission, worker_execution
from app.core.config import settings
from app.core.settings.workers import WorkersSettings
from app.domains.agents.repositories import LeaseLostError
from app.models.agent import AgentApproval, AgentRun, AgentStep, AgentToolCall
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.workers.base_task import TenantMismatchError
from app.workers.celery_app import BEAT_SCHEDULE, TASK_ROUTES


def test_settings_default_to_inline_and_route_agents_to_the_default_queue() -> None:
    defaults = WorkersSettings()
    assert defaults.agent_run_execution == "inline"
    assert defaults.celery_queue_agents == "default"
    assert defaults.agent_run_max_resumes == 3
    assert TASK_ROUTES["agents.run.execute"]["queue"] == settings.celery_queue_agents
    assert TASK_ROUTES["agents.run.resume"]["queue"] == settings.celery_queue_agents
    assert BEAT_SCHEDULE["agents-runs-reap"]["task"] == "agents.runs.reap"
    with pytest.raises(ValueError):
        WorkersSettings(celery_queue_agents="bad queue!")


def test_queued_run_completes_when_the_task_runs(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    queued = agent_env.run(run_id)
    assert queued.status == "queued"
    assert queued.request_snapshot["request"]["objective"] == "Answer the policy question"
    assert queued.request_snapshot["principal"]["roles"] == ["member"]

    result = agent_env.execute(run_id, seeded.organization_id)
    assert result.result == {"run_id": str(run_id), "status": "completed"}
    run = agent_env.run(run_id)
    assert run.status == "completed"
    assert run.lease_owner is None and run.lease_expires_at is None
    # The stored outcome is sanitised (``answer`` redacted) exactly as inline.
    assert run.outcome_json["mode"] == "answer" and run.outcome_json["not_found"] is False
    assert [s.sequence for s in agent_env.steps(run_id)] == [0, 1, 2]
    planning = agent_env.steps(run_id)[0]
    assert planning.observation_json == {"selected_document_ids": []}
    # A second delivery of the same message finds a terminal run and does nothing.
    again = agent_env.execute(run_id, seeded.organization_id)
    assert again.result["status"] == "not_runnable"
    assert agent_env.tools.calls == {"search": 1, "answer": 1}
    # Stream events were buffered in Redis for the run's organisation.
    keys = [k for k in agent_env.redis.keyspace.lists if str(seeded.organization_id) in k]
    assert keys, "events buffered under the organisation"


def test_kill_after_a_step_resumes_without_repeating_it(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)

    def _die(call_index: int) -> None:
        if call_index == 1:
            raise WorkerKilled("answer")

    agent_env.tools.before_answer = _die
    with pytest.raises(WorkerKilled):
        agent_env.execute(run_id, seeded.organization_id, task_id="exec-1")
    killed = agent_env.run(run_id)
    assert killed.status == "running" and killed.lease_owner == "exec-1"
    assert [(s.sequence, s.status) for s in agent_env.steps(run_id)] == [
        (0, "completed"),
        (1, "completed"),
        (2, "running"),
    ]

    # Redelivery with the same task id takes its own lease back and resumes at step 2.
    result = agent_env.execute(run_id, seeded.organization_id, task_id="exec-1")
    assert result.result["status"] == "completed"
    assert agent_env.tools.calls == {"search": 1, "answer": 2}
    steps = agent_env.steps(run_id)
    assert [(s.sequence, s.status) for s in steps] == [
        (0, "completed"),
        (1, "completed"),
        (2, "completed"),
    ]
    assert steps[2].error_message is None
    names = sorted(call.tool_name for call in agent_env.tool_calls(run_id))
    assert names == ["answer_from_context", "search_documents"]
    run = agent_env.run(run_id)
    assert run.observations_json["steps_executed"] == 2
    assert run.costs_json["total_tokens"] == 42


def test_side_effect_tool_runs_exactly_once_across_a_kill(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    agent_env.use_runtime(build_runtime(agent_env.tools, side_effect=True))
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    repository = agent_env.runtime._repository
    original = repository.update_agent_step
    armed = {"on": True}

    async def _update(session: Any, **kwargs: Any) -> Any:
        if armed["on"] and kwargs.get("status") == "completed" and kwargs.get("outputs"):
            if kwargs["outputs"].get("response"):
                armed["on"] = False
                raise WorkerKilled("after side effect")
        return await original(session, **kwargs)

    agent_env.monkeypatch.setattr(repository, "update_agent_step", _update)
    with pytest.raises(WorkerKilled):
        agent_env.execute(run_id, seeded.organization_id, task_id="exec-1")
    calls = agent_env.tool_calls(run_id)
    side_effect = [c for c in calls if c.tool_name == "answer_from_context"]
    assert [c.status for c in side_effect] == ["succeeded"]
    assert side_effect[0].idempotency_key_hash is not None

    # The worker died: the lease expires and another task takes the run over.
    agent_env.execute_sql(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(lease_expires_at=datetime.now(tz=UTC) - timedelta(seconds=5))
    )
    result = agent_env.execute(run_id, seeded.organization_id, task_id="exec-2")
    assert result.result["status"] == "completed"
    assert agent_env.tools.calls["answer"] == 1
    calls = agent_env.tool_calls(run_id)
    assert len([c for c in calls if c.tool_name == "answer_from_context"]) == 1
    assert agent_env.count(AgentStep, run_id) == 3
    assert agent_env.run(run_id).outcome_json["mode"] == "answer"


def test_lease_held_by_a_live_task_is_not_taken(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    agent_env.execute_sql(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(
            status="running",
            lease_owner="other-task",
            lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        )
    )
    result = agent_env.execute(run_id, seeded.organization_id, task_id="exec-9")
    assert result.result["status"] == "lease_held"
    assert agent_env.tools.calls == {"search": 0, "answer": 0}
    assert agent_env.run(run_id).lease_owner == "other-task"


def test_task_for_another_organisation_raises_tenant_mismatch(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    result = agent_env.execute(run_id, seeded.other_organization_id)
    assert result.failed()
    assert isinstance(result.result, TenantMismatchError)
    run = agent_env.run(run_id)
    assert run.status == "queued" and run.lease_owner is None
    assert agent_env.tools.calls == {"search": 0, "answer": 0}


def test_unknown_run_or_bad_ids_do_nothing(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    missing = agent_env.execute(seeded.user_id, seeded.organization_id)
    assert missing.result["status"] == "not_found"
    bad = agent_env.execute("not-a-uuid", seeded.organization_id)  # type: ignore[arg-type]
    assert bad.result["status"] == "not_found"


def test_downgraded_role_fails_with_principal_revoked(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    # answer_from_context needs member or above; the user is now a viewer.
    agent_env.execute_sql(
        update(OrganizationMember)
        .where(OrganizationMember.user_id == seeded.user_id)
        .values(role=OrganizationRole.viewer.value)
    )
    result = agent_env.execute(run_id, seeded.organization_id)
    assert result.result["status"] == "failed"
    run = agent_env.run(run_id)
    assert run.error_details_json["code"] == "principal_revoked"
    assert run.lease_owner is None
    assert agent_env.tools.calls == {"search": 0, "answer": 0}


def test_deactivated_user_fails_with_principal_revoked(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    agent_env.execute_sql(update(User).where(User.id == seeded.user_id).values(is_active=False))
    agent_env.execute(run_id, seeded.organization_id)
    assert agent_env.run(run_id).error_details_json["code"] == "principal_revoked"


def test_budget_still_stops_a_worker_run(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded, budget={"max_total_tokens": 10})
    result = agent_env.execute(run_id, seeded.organization_id)
    assert result.result["status"] == "failed"
    run = agent_env.run(run_id)
    assert run.error_details_json["code"] == "budget_exceeded"
    assert run.error_message == "Token budget exceeded"

    second = agent_env.submit(seeded, budget={"max_tool_calls": 1})
    agent_env.execute(second, seeded.organization_id, task_id="exec-2")
    assert agent_env.run(second).error_message == "Tool-call budget exceeded"


def test_cancel_between_steps_stops_the_run(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    pending_cancel = {"on": False}

    def _after_search() -> None:
        pending_cancel["on"] = True

    agent_env.tools.after_search = _after_search
    original = agent_env.runtime._worker_repository.read_status

    async def _read_status(session: Any, **kwargs: Any) -> Any:
        if pending_cancel["on"]:
            pending_cancel["on"] = False
            # Another connection commits the cancel, as POST /agent/runs/{id}/cancel does;
            # the worker must read it from the database, not from its identity map.
            async with agent_env.factory() as other:
                await other.execute(
                    update(AgentRun)
                    .where(AgentRun.id == kwargs["run_id"])
                    .values(status="cancelled", cancelled_at=datetime.now(tz=UTC))
                )
                await other.commit()
        return await original(session, **kwargs)

    agent_env.monkeypatch.setattr(agent_env.runtime._worker_repository, "read_status", _read_status)
    result = agent_env.execute(run_id, seeded.organization_id)
    assert result.result["status"] == "cancelled"
    assert agent_env.tools.calls == {"search": 1, "answer": 0}
    assert agent_env.run(run_id).lease_owner is None


def test_lost_lease_stops_without_further_writes(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)

    async def _renew(*args: Any, **kwargs: Any) -> None:
        raise LeaseLostError()

    agent_env.monkeypatch.setattr(worker_execution._worker, "renew", _renew)
    result = agent_env.execute(run_id, seeded.organization_id, task_id="exec-1")
    assert result.result["status"] == "lease_lost"
    run = agent_env.run(run_id)
    # Nothing after the lease was taken is committed; the reaper recovers the run later.
    assert run.status == "running" and run.lease_owner == "exec-1"
    assert agent_env.steps(run_id) == []


def test_unexpected_error_fails_the_run_safely(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)

    async def _boom(**kwargs: Any) -> Any:
        raise RuntimeError("secret detail that must not leak")

    agent_env.monkeypatch.setattr(agent_env.runtime, "execute_queued", _boom)
    result = agent_env.execute(run_id, seeded.organization_id)
    assert result.result["status"] == "failed"
    run = agent_env.run(run_id)
    assert run.error_details_json["code"] == "internal_error"
    assert "secret" not in (run.error_message or "")
    assert run.lease_owner is None


def test_unreadable_snapshot_fails_with_validation_error(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    agent_env.execute_sql(
        update(AgentRun).where(AgentRun.id == run_id).values(request_snapshot={"request": {}})
    )
    agent_env.execute(run_id, seeded.organization_id)
    assert agent_env.run(run_id).error_details_json["code"] == "validation_failed"


def test_inline_run_without_snapshot_is_not_executed(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    agent_env.execute_sql(
        update(AgentRun).where(AgentRun.id == run_id).values(request_snapshot=None)
    )
    assert agent_env.execute(run_id, seeded.organization_id).result["status"] == "not_runnable"


def _wait_for_approval(env: AgentWorkerEnv) -> tuple[Any, Any, AgentApproval]:
    env.use_runtime(build_runtime(env.tools, side_effect=True, approval=True))
    seeded = env.seed()
    run_id = env.submit(seeded)
    result = env.execute(run_id, seeded.organization_id)
    assert result.result["status"] == "waiting_approval"
    approvals = env.query(select_approvals(run_id))
    assert len(approvals) == 1
    return seeded, run_id, approvals[0]


def select_approvals(run_id: Any) -> Any:
    from sqlalchemy import select

    return select(AgentApproval).where(AgentApproval.agent_run_id == run_id)


def test_resume_after_approval_continues_the_run(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    seeded, run_id, approval = _wait_for_approval(agent_env)
    waiting = agent_env.run(run_id)
    assert waiting.status == "waiting_approval" and waiting.lease_owner is None
    assert agent_env.tools.calls == {"search": 1, "answer": 0}

    # Not approved yet: the resume task does nothing.
    early = agent_env.resume(run_id, seeded.organization_id, approval.id, task_id="res-0")
    assert early.result["status"] == "not_runnable"

    agent_env.execute_sql(
        update(AgentApproval).where(AgentApproval.id == approval.id).values(status="approved")
    )
    agent_env.execute_sql(update(AgentRun).where(AgentRun.id == run_id).values(status="queued"))
    result = agent_env.resume(run_id, seeded.organization_id, approval.id)
    assert result.result["status"] == "completed"
    assert agent_env.tools.calls == {"search": 1, "answer": 1}
    run = agent_env.run(run_id)
    assert run.request_snapshot["request"]["approval_ids"] == {
        "answer_from_context": str(approval.id)
    }
    steps = agent_env.steps(run_id)
    assert [(s.sequence, s.status) for s in steps] == [
        (0, "completed"),
        (1, "completed"),
        (2, "completed"),
    ]


def test_reaper_requeues_an_expired_lease_and_fails_after_the_limit(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    expired = datetime.now(tz=UTC) - timedelta(seconds=30)
    agent_env.execute_sql(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(status="running", lease_owner="dead-task", lease_expires_at=expired)
    )
    published: list[dict[str, Any]] = []

    class _Task:
        def delay(self, **kwargs: Any) -> None:
            published.append(kwargs)

    agent_env.monkeypatch.setattr("app.application.outbox.resolve_task", lambda name: _Task())
    counts = run_async_reap()
    assert counts == {"requeued": 1, "failed": 0}
    run = agent_env.run(run_id)
    assert (run.status, run.resume_count, run.lease_owner) == ("queued", 1, None)
    assert published == [{"run_id": str(run_id), "organization_id": str(seeded.organization_id)}]
    keys = [row.dedupe_key for row in agent_env.outbox(seeded.organization_id)]
    assert f"agents.run.execute:{run_id}:resume:1" in keys

    # The re-queued run is resumed by a new task.
    assert agent_env.execute(run_id, seeded.organization_id, task_id="exec-3").result["status"] == (
        "completed"
    )

    # A run that already used every resume fails with worker_lost.
    lost = agent_env.submit(seeded)
    agent_env.execute_sql(
        update(AgentRun)
        .where(AgentRun.id == lost)
        .values(
            status="running",
            lease_owner="dead-task",
            lease_expires_at=expired,
            resume_count=settings.agent_run_max_resumes,
        )
    )
    assert run_async_reap() == {"requeued": 0, "failed": 1}
    failed = agent_env.run(lost)
    assert failed.status == "failed"
    assert failed.error_details_json["code"] == "worker_lost"
    assert failed.lease_owner is None
    # Inline runs (no lease) and live leases are never touched.
    assert run_async_reap() == {"requeued": 0, "failed": 0}


def run_async_reap() -> dict[str, int]:
    from app.workers.async_runtime import run_async

    return run_async(run_reaper.reap_expired_runs())


def test_reap_task_and_submission_helpers(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    from app.workers import agent_tasks

    assert agent_tasks.reap_agent_runs.apply().result == {"requeued": 0, "failed": 0}
    assert run_submission.worker_mode()
    seeded = agent_env.seed()
    run_id = agent_env.submit(seeded)
    run = agent_env.run(run_id)
    assert run_submission.queued_result(run).status == "queued"
    assert not run_submission.can_resume(run)  # queued, not waiting for approval
    assert run.observations_json["execution"] == "worker"
    assert run.budget_json["max_steps"] == settings.agent_max_steps
    assert DOCUMENT_ID  # the fake search result document
    assert agent_env.count(AgentToolCall, run_id) == 0
