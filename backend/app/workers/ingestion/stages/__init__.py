"""Ingestion stages in run order (R06-01).

``extract -> clean_detect -> dlp -> chunk -> [graph_extract] -> embed -> index -> finalize``.
``graph_extract`` runs inline, after chunking and before embedding, and only when document
state is persisted (not during evaluation re-ingest), exactly where the single-pass worker
ran it.
"""

from __future__ import annotations

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
    StageName.graph_extract,
    StageName.embed,
    StageName.index,
    StageName.finalize,
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


def build_stages(options: IngestionOptions) -> list[Stage]:
    names = [
        name
        for name in STAGE_ORDER
        if name != StageName.graph_extract or options.persist_document_state
    ]
    return [
        Stage(name=name, run=_MODULES[name].run, on_skip=getattr(_MODULES[name], "on_skip", None))
        for name in names
    ]


__all__ = ["STAGE_ORDER", "Stage", "StageName", "StageOutcome", "build_stages"]
