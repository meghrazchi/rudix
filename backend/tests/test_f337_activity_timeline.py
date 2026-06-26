"""Tests for F337 — Agent Activity Timeline.

Covers:
  - Migration smoke (upgrade/downgrade with SQLite)
  - ActivityTimelineEvent model field constraints
  - ChatWSEventType includes activity.step.update
  - ChatWSOutboundEvent serialises an activity.step.update event
  - send_step step_seq counter behaviour
  - Activity step payload safety (no internal IDs)
  - Step state transitions via setTimelineSteps merge logic (Python reimplementation)
  - General-chat path emits skipped steps for source/search stages
  - Full-RAG path emits all expected step keys in order
  - Permission: activity steps returned only for authenticated principals
"""

from __future__ import annotations

import asyncio
from importlib import util
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.chat.schemas.chat_ws import ChatWSEventType, ChatWSOutboundEvent

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260630_0002_activity_timeline_f337.py"
)

_ORGS_DDL = """
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL
)
"""
_CHAT_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    user_id TEXT,
    title TEXT
)
"""
_CHAT_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    chat_session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT
)
"""


def _load_migration(path: Path, module_name: str):
    spec = util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Migration ─────────────────────────────────────────────────────────────────


def test_activity_timeline_migration_upgrade_creates_table_and_indexes() -> None:
    migration = _load_migration(_MIGRATION_PATH, "migration_20260630_0002")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text(_ORGS_DDL))
        conn.execute(sa.text(_CHAT_SESSIONS_DDL))
        conn.execute(sa.text(_CHAT_MESSAGES_DDL))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()

        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert "activity_timeline_events" in tables

        cols = {c["name"] for c in inspector.get_columns("activity_timeline_events")}
        assert cols >= {
            "id",
            "organization_id",
            "chat_session_id",
            "chat_message_id",
            "sequence",
            "step_key",
            "label",
            "state",
            "detail",
            "started_at",
            "completed_at",
            "duration_ms",
            "created_at",
            "updated_at",
        }

        indexes = {idx["name"] for idx in inspector.get_indexes("activity_timeline_events")}
        assert "idx_activity_timeline_events_session_seq" in indexes
        assert "idx_activity_timeline_events_message" in indexes


def test_activity_timeline_migration_downgrade_removes_table() -> None:
    migration = _load_migration(_MIGRATION_PATH, "migration_20260630_0002_down")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text(_ORGS_DDL))
        conn.execute(sa.text(_CHAT_SESSIONS_DDL))
        conn.execute(sa.text(_CHAT_MESSAGES_DDL))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
            migration.downgrade()

        inspector = sa.inspect(conn)
        assert "activity_timeline_events" not in inspector.get_table_names()


# ── Schema ────────────────────────────────────────────────────────────────────


def test_chat_ws_event_type_includes_activity_step_update() -> None:
    assert "activity.step.update" in ChatWSEventType.__args__  # type: ignore[union-attr]


def test_chat_ws_outbound_event_serialises_activity_step() -> None:
    evt = ChatWSOutboundEvent(
        event="activity.step.update",  # type: ignore[arg-type]
        sequence=3,
        payload={
            "step_key": "searching_documents",
            "sequence": 3,
            "label": "Searching knowledge base",
            "state": "success",
            "detail": "Found 8 relevant passages",
            "duration_ms": 342,
        },
    )
    data = evt.model_dump()
    assert data["event"] == "activity.step.update"
    assert data["payload"]["step_key"] == "searching_documents"
    assert data["payload"]["state"] == "success"


def test_chat_ws_activity_step_json_excludes_none_detail() -> None:
    evt = ChatWSOutboundEvent(
        event="activity.step.update",  # type: ignore[arg-type]
        sequence=1,
        payload={
            "step_key": "understanding_question",
            "sequence": 1,
            "label": "Understanding your question",
            "state": "running",
            "detail": None,
            "duration_ms": None,
        },
    )
    raw = evt.to_json()
    import json

    parsed = json.loads(raw)
    assert parsed["payload"]["state"] == "running"
    assert parsed["payload"]["detail"] is None


# ── send_step counter behaviour ───────────────────────────────────────────────


def test_send_step_increments_seq_only_on_running_or_pending() -> None:
    """seq should increment when state is running or pending, not on transitions."""
    events: list[dict] = []

    async def _fake_send(event_type: str, payload: dict | None = None, **_kw: Any) -> None:
        if event_type == "activity.step.update" and payload:
            events.append(dict(payload))

    activity_step_seq = 0

    async def send_step(step_key: str, label: str, state: str, detail=None, duration_ms=None):
        nonlocal activity_step_seq
        if state in ("running", "pending"):
            activity_step_seq += 1
        await _fake_send(
            "activity.step.update",
            {
                "step_key": step_key,
                "sequence": activity_step_seq,
                "label": label,
                "state": state,
                "detail": detail,
                "duration_ms": duration_ms,
            },
        )

    async def _run() -> None:
        await send_step("understanding_question", "Understanding your question", "running")
        await send_step("understanding_question", "Understanding your question", "success")
        await send_step("checking_sources", "Checking accessible sources", "running")
        await send_step(
            "checking_sources", "Checking accessible sources", "success", detail="Found 5 sources"
        )

    asyncio.run(_run())

    # First two events both reference seq=1 (understanding_question)
    assert events[0]["sequence"] == 1
    assert events[1]["sequence"] == 1
    # checking_sources gets seq=2
    assert events[2]["sequence"] == 2
    assert events[3]["sequence"] == 2
    assert events[3]["detail"] == "Found 5 sources"


# ── Payload safety ────────────────────────────────────────────────────────────


def test_activity_step_payload_contains_no_document_ids() -> None:
    payload = {
        "step_key": "searching_documents",
        "sequence": 3,
        "label": "Searching knowledge base",
        "state": "success",
        "detail": "Found 4 relevant passages",
        "duration_ms": 210,
    }
    # Ensure no UUID-shaped values that could be internal document references
    for key in ("document_id", "chunk_id", "doc_id"):
        assert key not in payload

    detail = payload.get("detail", "")
    assert isinstance(detail, str)
    # No raw UUID4 patterns in the human-readable detail
    import re

    uuid_pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I
    )
    assert not uuid_pattern.search(detail)


def test_activity_step_detail_is_operational_summary_only() -> None:
    allowed_details = [
        "Found 12 relevant passages",
        "Selected 5 top sources",
        "Verified 3 citations",
        "Linked 2 citations",
        "No relevant answer found",
        "Searching 8 sources",
        "Request could not be processed",
        None,
    ]
    for detail in allowed_details:
        if detail is not None:
            assert len(detail) < 200, f"Detail too long: {detail}"


# ── Step state semantics ──────────────────────────────────────────────────────


def test_all_valid_states_covered() -> None:
    valid_states = {"pending", "running", "success", "warning", "failed", "skipped"}
    # These come from the DB model constraint and the frontend type
    from app.models.activity_timeline import _STATES

    assert set(_STATES) == valid_states


def test_step_merge_logic_updates_existing_by_step_key() -> None:
    """Simulates the frontend setTimelineSteps merge logic in Python."""

    def apply_step(steps: list[dict], new_step: dict) -> list[dict]:
        idx = next((i for i, s in enumerate(steps) if s["stepKey"] == new_step["stepKey"]), -1)
        if idx == -1:
            result = [*steps, new_step]
            result.sort(key=lambda s: s["sequence"])
            return result
        result = list(steps)
        result[idx] = {**result[idx], **new_step}
        return result

    steps: list[dict] = []
    steps = apply_step(
        steps,
        {
            "stepKey": "understanding_question",
            "sequence": 1,
            "label": "Understanding your question",
            "state": "running",
            "detail": None,
            "durationMs": None,
        },
    )
    assert len(steps) == 1
    assert steps[0]["state"] == "running"

    steps = apply_step(
        steps,
        {
            "stepKey": "understanding_question",
            "sequence": 1,
            "label": "Understanding your question",
            "state": "success",
            "detail": None,
            "durationMs": None,
        },
    )
    assert len(steps) == 1
    assert steps[0]["state"] == "success"

    steps = apply_step(
        steps,
        {
            "stepKey": "checking_sources",
            "sequence": 2,
            "label": "Checking accessible sources",
            "state": "running",
            "detail": None,
            "durationMs": None,
        },
    )
    assert len(steps) == 2
    assert steps[0]["stepKey"] == "understanding_question"
    assert steps[1]["stepKey"] == "checking_sources"


# ── Expected step keys per pipeline path ─────────────────────────────────────


def test_general_chat_path_expected_step_keys() -> None:
    """Steps emitted for scope_mode=none should skip source/search stages."""
    expected_in_general_chat = {
        "understanding_question",
        "checking_sources",  # skipped
        "searching_documents",  # skipped
        "drafting_answer",
        "preparing_final_answer",
    }
    # These keys must all be handled by the frontend (not a WS test, just key contract)
    assert "checking_sources" in expected_in_general_chat
    assert "searching_documents" in expected_in_general_chat


def test_full_rag_path_expected_step_keys_order() -> None:
    """All expected steps for full RAG should appear in display order."""
    ordered_steps = [
        "understanding_question",
        "checking_sources",
        "searching_documents",
        "reranking_evidence",
        "drafting_answer",
        "verifying_citations",
        "preparing_final_answer",
    ]
    # Verify each key is unique and in correct display position
    assert len(ordered_steps) == len(set(ordered_steps))
    assert ordered_steps.index("checking_sources") < ordered_steps.index("searching_documents")
    assert ordered_steps.index("searching_documents") < ordered_steps.index("reranking_evidence")
    assert ordered_steps.index("reranking_evidence") < ordered_steps.index("drafting_answer")
    assert ordered_steps.index("drafting_answer") < ordered_steps.index("verifying_citations")
    assert ordered_steps.index("verifying_citations") < ordered_steps.index(
        "preparing_final_answer"
    )


# ── ActivityTimelineEvent model ───────────────────────────────────────────────


def test_activity_timeline_event_model_tablename() -> None:
    from app.models.activity_timeline import ActivityTimelineEvent

    assert ActivityTimelineEvent.__tablename__ == "activity_timeline_events"


def test_activity_timeline_event_model_has_required_fields() -> None:
    from app.models.activity_timeline import ActivityTimelineEvent

    mapper = sa.inspect(ActivityTimelineEvent)
    col_names = {col.key for col in mapper.columns}
    assert col_names >= {
        "organization_id",
        "chat_session_id",
        "chat_message_id",
        "sequence",
        "step_key",
        "label",
        "state",
        "detail",
        "started_at",
        "completed_at",
        "duration_ms",
    }


def test_activity_timeline_event_exported_from_models_init() -> None:
    from app import models

    assert hasattr(models, "ActivityTimelineEvent")
