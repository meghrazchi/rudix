#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema, or check a committed copy against it.

No services are started. Required config fields that have no default get stub
values so pydantic-settings can load without live infrastructure. Two values
are forced (not defaulted) before the app is imported, because they change the
route table itself:

- ``ENVIRONMENT=development``: ``ENVIRONMENT=test`` mounts extra alias routes;
- ``API_PREFIX=/api/v1``: the frontend's generated types use this prefix.

pydantic-settings still reads ``.env`` files (project root and ``backend/``)
for every other field, so a local ``.env`` can change ``info.title``
(``API_NAME``) or ``info.version`` (``API_VERSION``). CI has no ``.env``; if a
local ``--check`` reports only an ``info`` difference, check your ``.env``.

Usage:
    python scripts/export_openapi.py [output]       # output: file path or '-' (stdout)
    python scripts/export_openapi.py --check PATH   # exit 1 if PATH differs from the app

``--check`` compares parsed JSON, so formatting (for example Prettier on
``frontend/openapi.json``) never causes a failure. It prints the added, removed
and changed paths and component schemas, at most 50 lines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# Stub every required field that has no default. These values satisfy
# pydantic type validation and are never used for actual connections.
_STUBS: dict[str, str] = {
    "API_BASE_URL": "http://localhost:8000",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "postgresql+asyncpg://x:x@localhost/x",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "documents",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "MINIO_BUCKET": "documents",
    "RABBITMQ_URL": "amqp://x:x@localhost:5672//",
    "REDIS_URL": "redis://localhost:6379/0",
}

# Forced: these decide which routes exist and under which prefix.
_FORCED: dict[str, str] = {
    "ENVIRONMENT": "development",
    "API_PREFIX": "/api/v1",
}

MAX_REPORT_LINES = 50

SchemaLoader = Callable[[], dict[str, Any]]


def prepare_environment(environ: dict[str, str] | None = None) -> None:
    """Apply the stub defaults and the forced values to ``environ``."""
    target = os.environ if environ is None else environ
    for key, value in _STUBS.items():
        target.setdefault(key, value)
    for key, value in _FORCED.items():
        target[key] = value


def load_app_schema() -> dict[str, Any]:
    """Import the app with the export environment and return its OpenAPI dict."""
    prepare_environment()
    from app.main import app

    return app.openapi()


def serialize(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2) + "\n"


def _section(schema: dict[str, Any], *keys: str) -> dict[str, Any]:
    node: Any = schema
    for key in keys:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def _diff_keys(label: str, committed: dict[str, Any], live: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for name in sorted(live.keys() - committed.keys()):
        lines.append(f"+ {label} added: {name}")
    for name in sorted(committed.keys() - live.keys()):
        lines.append(f"- {label} removed: {name}")
    for name in sorted(committed.keys() & live.keys()):
        if committed[name] != live[name]:
            lines.append(f"~ {label} changed: {name}")
    return lines


def diff_schemas(committed: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Describe how ``committed`` differs from ``live``; empty when they match."""
    lines = _diff_keys("path", _section(committed, "paths"), _section(live, "paths"))
    lines += _diff_keys(
        "schema",
        _section(committed, "components", "schemas"),
        _section(live, "components", "schemas"),
    )
    if not lines and committed != live:
        # Anything else (info, tags, security schemes, ...): name the key.
        for label, old, new, skip in (
            ("top-level", committed, live, {"paths", "components"}),
            (
                "components",
                _section(committed, "components"),
                _section(live, "components"),
                {"schemas"},
            ),
        ):
            for key in sorted((old.keys() | new.keys()) - skip):
                if old.get(key) != new.get(key):
                    lines.append(f"~ {label} changed: {key}")
    return lines


def check(path: Path, live: dict[str, Any]) -> int:
    """Compare the committed JSON at ``path`` with ``live``; return the exit code."""
    try:
        committed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"OpenAPI check: {path} does not exist.", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"OpenAPI check: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 1
    lines = diff_schemas(committed, live)
    if not lines:
        print(f"OpenAPI check: {path} matches the app schema.", file=sys.stderr)
        return 0
    print(f"OpenAPI check: {path} differs from the app schema:", file=sys.stderr)
    for line in lines[:MAX_REPORT_LINES]:
        print(f"  {line}", file=sys.stderr)
    if len(lines) > MAX_REPORT_LINES:
        print(f"  ... and {len(lines) - MAX_REPORT_LINES} more", file=sys.stderr)
    print(
        "Regenerate it: cd frontend && npm run api:update-schema",
        file=sys.stderr,
    )
    return 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help="file to write the schema to, or '-' for stdout (default)",
    )
    parser.add_argument(
        "--check",
        metavar="PATH",
        type=Path,
        help="compare the committed schema at PATH with the app; exit 1 on difference",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, loader: SchemaLoader = load_app_schema) -> int:
    args = _parse_args(argv)
    schema = loader()
    if args.check is not None:
        return check(args.check, schema)
    serialized = serialize(schema)
    if args.output == "-":
        sys.stdout.write(serialized)
    else:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(serialized, encoding="utf-8")
        print(f"OpenAPI schema written to {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Running as a script puts scripts/ (not backend/) on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
