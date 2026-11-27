"""State carried across the transactions of one sync run (R06-11).

Nothing here is an ORM object: every transaction loads the rows it writes, so a run can
span many sessions. The persisted checkpoint is ``connector_sync_runs.checkpoint_cursor``:
the provider cursor for the next page, or ``{"_rudix_phase": "finalize", "cursor_after":
...}`` once paging is done (a resumed full sync then only tombstones and completes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.models.connector_sync import ConnectorSyncRun

PHASE_KEY = "_rudix_phase"
PHASE_FINALIZE = "finalize"


@dataclass
class LoopState:
    cursor: dict
    items_seen: int = 0
    items_upserted: int = 0
    items_deleted: int = 0
    pages_committed: int = 0
    paging_done: bool = False
    cursor_after: dict = field(default_factory=dict)
    resumed: bool = False

    def counters(self) -> dict[str, int]:
        return {
            "items_seen": self.items_seen,
            "items_upserted": self.items_upserted,
            "items_deleted": self.items_deleted,
        }

    @classmethod
    def from_run(cls, run: ConnectorSyncRun, *, start_cursor: dict) -> LoopState:
        """Continue from the run's checkpoint with its persisted counters, or start fresh."""
        checkpoint = run.checkpoint_cursor
        if checkpoint is None:
            return cls(cursor=dict(start_cursor))
        state = cls(
            cursor=dict(checkpoint),
            items_seen=run.items_seen or 0,
            items_upserted=run.items_upserted or 0,
            items_deleted=run.items_deleted or 0,
            pages_committed=run.pages_committed or 0,
            resumed=True,
        )
        if checkpoint.get(PHASE_KEY) == PHASE_FINALIZE:
            state.paging_done = True
            state.cursor_after = dict(checkpoint.get("cursor_after") or {})
        return state


def finalize_checkpoint(cursor_after: dict) -> dict:
    return {PHASE_KEY: PHASE_FINALIZE, "cursor_after": dict(cursor_after)}


@dataclass
class RunContext:
    run_id: UUID
    organization_id: UUID
    connection_id: UUID
    sync_job_id: UUID
    owner: str
    adapter: Any
    decrypted: dict
    provider_key: str | None
    provider_source_id: str | None
    external_source_id: UUID | None
    incremental: bool
    has_credential: bool
    state: LoopState

    @property
    def mode(self) -> str:
        return "incremental" if self.incremental else "full"
