"""Ingestion stages in run order (R06-01).

``extract -> clean_detect -> dlp -> chunk -> embed -> index -> finalize -> [graph_extract]``.
``graph_extract`` runs after ``finalize`` (0.6.0 part 2; in chain mode as its own task on
its own queue) and only when document state is persisted (not during evaluation
re-ingest). Its failure sets ``graph_extraction_status=failed`` and never fails the
document.
"""

from __future__ import annotations

from typing import Any

from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.stages import (
    chunk,
    clean_detect,
    dlp,
    embed,
    extract,
    finalize,
    graph_extract,
    index,
)
from app.workers.ingestion.stages.base import Stage, StageName, StageOutcome

STAGE_ORDER: tuple[StageName, ...] = (
    StageName.extract,
    StageName.clean_detect,
    StageName.dlp,
    StageName.chunk,
    StageName.embed,
    StageName.index,
    StageName.finalize,
    StageName.graph_extract,
)

# Modules, not functions: ``run`` is looked up per build so a replaced ``run`` takes effect.
_MODULES = {
    StageName.extract: extract,
    StageName.clean_detect: clean_detect,
    StageName.dlp: dlp,
    StageName.chunk: chunk,
    StageName.graph_extract: graph_extract,
    StageName.embed: embed,
    StageName.index: index,
    StageName.finalize: finalize,
}


def stage_module(name: StageName) -> Any:
    return _MODULES[name]


def build_stage(name: StageName) -> Stage:
    module = _MODULES[name]
    return Stage(name=name, run=module.run, on_skip=getattr(module, "on_skip", None))


def build_stages(options: IngestionOptions) -> list[Stage]:
    names = [
        name
        for name in STAGE_ORDER
        if name != StageName.graph_extract or options.persist_document_state
    ]
    return [build_stage(name) for name in names]


__all__ = [
    "STAGE_ORDER",
    "Stage",
    "StageName",
    "StageOutcome",
    "build_stage",
    "build_stages",
    "stage_module",
]
