"""Release workflow: optional single frontend image (R08-11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RELEASE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
SINGLE = "vars.RUDIX_FRONTEND_IMAGE_MODE == 'single'"
DEFAULT = "vars.RUDIX_FRONTEND_IMAGE_MODE != 'single'"


def _build_steps() -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load(RELEASE.read_text())
    steps = workflow["jobs"]["build-images"]["steps"]
    return {step["name"]: step for step in steps if "name" in step}


def test_default_keeps_one_frontend_image_per_environment() -> None:
    steps = _build_steps()
    for name in (
        "Build and push frontend staging image",
        "Build and push frontend production image",
    ):
        assert steps[name]["if"] == DEFAULT
        assert "NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE" not in steps[name]["run"]


def test_single_mode_builds_one_request_mode_image_for_both_digests() -> None:
    steps = _build_steps()
    single = steps["Build and push single frontend image (request mode)"]
    assert single["if"] == SINGLE
    run = single["run"]
    assert "NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE=request" in run
    assert single["env"]["RUDIX_PUBLIC_SITE_URL"] == "${{ vars.RUDIX_PUBLIC_SITE_URL }}"
    assert run.count("docker buildx build") == 1
    assert "frontend-staging:${GITHUB_SHA}" in run
    assert "frontend-production:${GITHUB_SHA}" in run
    assert "frontend-production.json" in run
    names = list(steps)
    assert names.index("Build and push single frontend image (request mode)") < names.index(
        "Resolve pushed image digests"
    )
