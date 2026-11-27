"""Stage names, outcome, and stage descriptor (R06-01)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.workers.ingestion.context import StageContext


class StageName(StrEnum):
    extract = "extract"
    clean_detect = "clean_detect"
    dlp = "dlp"
    chunk = "chunk"
    graph_extract = "graph_extract"
    embed = "embed"
    index = "index"
    finalize = "finalize"


@dataclass
class StageOutcome:
    # Counts and configuration only, never document text.
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_ref: str | None = None
    # True when the stage marked its own row completed inside its transaction (finalize).
    marked: bool = False


@dataclass(frozen=True)
class Stage:
    name: StageName
    run: Callable[[StageContext], Awaitable[StageOutcome]]


# Producer stage -> stages that read its artifacts. A completed producer whose artifact parts
# are missing while one of its consumers has not completed is run again.
ARTIFACT_CONSUMERS: dict[StageName, tuple[StageName, ...]] = {
    StageName.extract: (StageName.clean_detect, StageName.chunk),
    StageName.clean_detect: (StageName.dlp, StageName.chunk),
    StageName.embed: (StageName.finalize,),
}
