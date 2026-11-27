"""R04-13 guard: persistence lives in repositories/workflows, not these routers.

Text scan on purpose: a regression (a new ``select(`` or ``.commit(`` in a router) fails
fast without importing the app. ``auth.py`` (18 commits, auth-critical) and
``agent_runs.py`` (agent execution moves to workers in R06-13) are deferred.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HTTP_DIR = Path(__file__).resolve().parents[1] / "app" / "interfaces" / "http"
GUARDED = ["documents.py", "admin.py", "evaluations.py"]
FORBIDDEN = ["select(", ".commit("]


@pytest.mark.parametrize("filename", GUARDED)
def test_router_has_no_direct_persistence(filename: str) -> None:
    source = (HTTP_DIR / filename).read_text()
    found = [token for token in FORBIDDEN if token in source]
    assert found == [], f"{filename} must delegate to repositories/workflows, found {found}"
