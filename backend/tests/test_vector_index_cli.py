"""Operator CLI ``scripts/vector_index.py`` (R06-08)."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from vector_index_support import ALIAS, NEW_MODEL, NEW_SIZE, VectorIndexEnv, make_vector_index_env

from app.core.config import settings
from app.workers import vector_index_tasks

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vector_index.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("script_vector_index", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vi(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    yield from make_vector_index_env(ingestion_env, monkeypatch)


def _cli(vi: VectorIndexEnv, *argv: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    code = vi.run(_load().run(list(argv), out=out))
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    return code, json.loads(lines[-1])


def test_operator_flow_through_the_cli(vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    vi.seed_indexed("doc")
    code, payload = _cli(vi, "status")
    assert code == 2 and payload["error"] == "legacy_mode"

    vi.enable_alias()
    code, adopted = _cli(vi, "adopt")
    assert code == 0 and adopted["generation"] == 1 and adopted["state"] == "active"

    vi.configure_model(NEW_MODEL, NEW_SIZE)
    code, plan = _cli(vi, "plan")
    assert code == 0 and plan["would_create"]["generation"] == 2
    assert plan["would_create"]["vector_size"] == NEW_SIZE
    assert set(vi.generations()) == {1}  # plan writes nothing

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        vector_index_tasks.build_vector_index,
        "apply_async",
        lambda kwargs=None, **_: sent.append(kwargs or {}),
    )
    code, enqueued = _cli(vi, "build", "--enqueue")
    assert code == 0 and enqueued == {"enqueued": True, "generation": 2}
    assert sent == [{"generation": 2, "max_pages": None}]

    code, built = _cli(vi, "build", "--generation", "2")
    assert code == 0 and built["finished"] is True and built["verified"] is True

    code, dry = _cli(vi, "swap")
    assert code == 0 and dry["mode"] == "DRY RUN" and dry["applied"] is False
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    code, swapped = _cli(vi, "swap", "--yes")
    assert code == 0 and swapped["applied"] is True
    assert vi.client.aliases[ALIAS] != settings.qdrant_collection

    code, status = _cli(vi, "status")
    assert status["alias_target"] == vi.client.aliases[ALIAS]
    assert [g["state"] for g in status["generations"]] == ["retired", "active"]

    code, rolled = _cli(vi, "rollback")
    assert rolled["mode"] == "DRY RUN" and rolled["to_generation"] == 1
    code, rolled = _cli(vi, "rollback", "--yes")
    assert rolled["applied"] is True
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}

    code, dropped = _cli(vi, "drop-retired")
    assert code == 0 and dropped == {"generations": [], "mode": "DRY RUN"}
    monkeypatch.setattr(settings, "qdrant_retired_grace_hours", 0)
    code, again = _cli(vi, "rollback", "--yes")  # back to generation 2; 1 is retired
    assert again["to_generation"] == 2
    code, dropped = _cli(vi, "drop-retired", "--yes")
    assert dropped == {"generations": [1], "mode": "APPLY"}


def test_cli_rejects_a_bad_page_count() -> None:
    with pytest.raises(SystemExit):
        _load()._parse_args(["build", "--max-pages", "0"])
