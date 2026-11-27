"""0.6.0 worker settings and ingestion stage metrics (R06-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core import metrics_workers
from app.core.config import Settings, settings
from app.core.settings.workers import WorkersSettings


def test_workers_settings_defaults_and_composition() -> None:
    defaults = WorkersSettings()
    assert defaults.ingest_stage_lease_seconds == 900
    assert defaults.ingest_embed_batch_chunks == 96
    assert defaults.ingest_artifact_max_part_bytes == 8 * 1024 * 1024
    assert issubclass(Settings, WorkersSettings)
    assert settings.ingest_embed_batch_chunks >= 1


@pytest.mark.parametrize("value", [0, 2049])
def test_embed_batch_chunks_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        WorkersSettings(ingest_embed_batch_chunks=value)


def _sample(stage: str, outcome: str) -> float:
    value = metrics_workers.registry.get_sample_value(
        "rudix_ingest_stage_seconds_count", {"stage": stage, "outcome": outcome}
    )
    return float(value or 0.0)


def test_record_ingest_stage_observes_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before = _sample("embed", "completed")
    metrics_workers.record_ingest_stage("embed", "completed", 0.25)
    assert _sample("embed", "completed") == before + 1


def test_record_ingest_stage_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    before = _sample("chunk", "skipped")
    metrics_workers.record_ingest_stage("chunk", "skipped", 0.1)
    assert _sample("chunk", "skipped") == before


def test_record_ingest_stage_swallows_label_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)

    class _Broken:
        def labels(self, **_: str) -> None:
            raise ValueError("bad label")

    monkeypatch.setattr(metrics_workers, "INGEST_STAGE_SECONDS", _Broken())
    metrics_workers.record_ingest_stage("extract", "failed", 1.0)
