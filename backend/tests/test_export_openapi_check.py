"""``scripts/export_openapi.py`` export and ``--check`` (R03-10)."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "export_openapi.py"


@pytest.fixture
def exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_openapi_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Rudix", "version": "0.3.0"},
        "paths": {
            "/api/v1/health": {"get": {"operationId": "health"}},
            "/api/v1/chat": {"post": {"operationId": "chat"}},
        },
        "components": {
            "schemas": {
                "ChatResponse": {"type": "object", "properties": {"answer": {"type": "string"}}},
                "Health": {"type": "object"},
            },
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        },
    }


def _write(path: Path, schema: dict[str, Any], *, indent: int | None = 2) -> Path:
    path.write_text(json.dumps(schema, indent=indent), encoding="utf-8")
    return path


def test_check_passes_when_schemas_match(
    exporter: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _write(tmp_path / "openapi.json", _schema())

    code = exporter.main(["--check", str(committed)], loader=_schema)

    assert code == 0
    assert "matches" in capsys.readouterr().err


def test_check_fails_when_a_path_is_removed(
    exporter: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = _schema()
    del stale["paths"]["/api/v1/chat"]
    committed = _write(tmp_path / "openapi.json", stale)

    code = exporter.main(["--check", str(committed)], loader=_schema)

    assert code == 1
    assert "+ path added: /api/v1/chat" in capsys.readouterr().err


def test_check_ignores_formatting_and_key_order(exporter: ModuleType, tmp_path: Path) -> None:
    schema = _schema()
    reordered = dict(reversed(list(schema.items())))
    committed = tmp_path / "openapi.json"
    committed.write_text(
        json.dumps(reordered, indent=None, separators=(",", ":")) + "\n\n", encoding="utf-8"
    )

    assert exporter.check(committed, _schema()) == 0


def test_diff_reports_added_removed_and_changed(exporter: ModuleType) -> None:
    live = _schema()
    committed = copy.deepcopy(live)
    committed["paths"]["/api/v1/old"] = {"get": {}}
    committed["components"]["schemas"]["ChatResponse"]["properties"]["dummy"] = {"type": "string"}
    del committed["components"]["schemas"]["Health"]

    lines = exporter.diff_schemas(committed, live)

    assert lines == [
        "- path removed: /api/v1/old",
        "+ schema added: Health",
        "~ schema changed: ChatResponse",
    ]


def test_diff_names_other_changed_sections(exporter: ModuleType) -> None:
    live = _schema()
    committed = copy.deepcopy(live)
    committed["info"]["version"] = "0.1.0"
    committed["components"]["securitySchemes"] = {}

    assert exporter.diff_schemas(committed, live) == [
        "~ top-level changed: info",
        "~ components changed: securitySchemes",
    ]


def test_check_caps_report_lines(
    exporter: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _schema()
    live["paths"].update({f"/api/v1/p{i:03d}": {} for i in range(80)})
    committed = _write(tmp_path / "openapi.json", _schema())

    assert exporter.check(committed, live) == 1
    err = capsys.readouterr().err
    assert err.count("path added") == exporter.MAX_REPORT_LINES
    assert "... and 30 more" in err


@pytest.mark.parametrize("content", [None, "{not json"])
def test_check_fails_on_missing_or_invalid_file(
    exporter: ModuleType, tmp_path: Path, content: str | None
) -> None:
    committed = tmp_path / "openapi.json"
    if content is not None:
        committed.write_text(content, encoding="utf-8")

    assert exporter.check(committed, _schema()) == 1


def test_export_writes_file_and_stdout(
    exporter: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "nested" / "openapi.json"

    assert exporter.main([str(dest)], loader=_schema) == 0
    assert json.loads(dest.read_text(encoding="utf-8")) == _schema()

    assert exporter.main([], loader=_schema) == 0
    assert json.loads(capsys.readouterr().out) == _schema()


def test_prepare_environment_forces_route_settings(exporter: ModuleType) -> None:
    environ = {"ENVIRONMENT": "test", "API_PREFIX": "/x", "DATABASE_URL": "kept"}

    exporter.prepare_environment(environ)

    assert environ["ENVIRONMENT"] == "development"
    assert environ["API_PREFIX"] == "/api/v1"
    assert environ["DATABASE_URL"] == "kept"
    assert environ["REDIS_URL"] == exporter._STUBS["REDIS_URL"]
    assert environ["OPENAI_API_KEY"] == exporter._STUBS["OPENAI_API_KEY"]


def test_script_exports_real_app_without_test_aliases(exporter: ModuleType, tmp_path: Path) -> None:
    """End to end: run as a script with ENVIRONMENT=test inherited; --check passes.

    OPENAI_API_KEY is removed, as on a CI runner with no .env: the export must stub it.
    """
    dest = tmp_path / "openapi.json"
    env = {**os.environ, "ENVIRONMENT": "test", "API_PREFIX": "/elsewhere"}
    env.pop("OPENAI_API_KEY", None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(dest)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    schema = json.loads(dest.read_text(encoding="utf-8"))
    assert schema["paths"], "export produced no paths"
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    assert exporter.check(dest, schema) == 0
