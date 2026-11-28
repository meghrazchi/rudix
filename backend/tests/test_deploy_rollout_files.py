"""Deploy paths ship the RabbitMQ configuration and stop the replaced worker (R06-03, R06-04).

Staging and production mount ``./rabbitmq/rabbitmq.conf`` and ``./rabbitmq/enabled_plugins``
next to the compose file; a deploy path that does not copy them leaves Docker to create
empty directories there and RabbitMQ does not start. The 0.6.0 pools replace the single
``worker`` service, which keeps running unless ``up`` removes orphans.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TERRAFORM = _REPO / "deploy" / "terraform" / "main.tf"
_REMOTE_SCRIPT = _REPO / "deploy" / "scripts" / "deploy_compose_remote.sh"
_RABBITMQ_FILES = ("rabbitmq.conf", "enabled_plugins")


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path.name} is not part of this checkout")
    return path.read_text(encoding="utf-8")


def _compose_up_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.search(r"docker compose .* up -d", line)]


def test_terraform_rollout_uploads_the_rabbitmq_configuration() -> None:
    text = _read(_TERRAFORM)
    assert "mkdir -p '${var.app_path}/rabbitmq'" in text
    for name in _RABBITMQ_FILES:
        assert f'source      = "${{local.rabbitmq_config_dir}}/{name}"' in text
        assert f'destination = "${{var.app_path}}/rabbitmq/{name}"' in text
        # A changed file triggers a rollout.
        assert f'filesha256("${{local.rabbitmq_config_dir}}/{name}")' in text
    for name in _RABBITMQ_FILES:
        assert (_REPO / "infra" / "rabbitmq" / name).is_file()


def test_every_full_compose_up_removes_orphans() -> None:
    terraform = _compose_up_lines(_read(_TERRAFORM))
    # The first `up` starts only the infrastructure services before migrations.
    full = [line for line in terraform if "infra_services" not in line]
    assert full and all("--remove-orphans" in line for line in full)
    remote = _compose_up_lines(_read(_REMOTE_SCRIPT))
    assert remote and all("--remove-orphans" in line for line in remote)


# --- 0.8.0 edge proxy and profiles (R08-01, R08-12) ---------------------------------------

_EDGE_FILES = (
    "Caddyfile",
    "tls_acme",
    "tls_files",
    "noindex_true",
    "noindex_false",
    "matomo_on",
    "matomo_off",
)
_RELEASE = _REPO / ".github" / "workflows" / "release.yml"
_VARIABLES = _REPO / "deploy" / "terraform" / "variables.tf"
_CHECK_COMPOSE = _REPO / "deploy" / "scripts" / "check_compose_config.sh"
_CHECK_ENV = _REPO / "deploy" / "scripts" / "check_deploy_env.sh"


def test_terraform_uploads_and_hashes_the_edge_configuration() -> None:
    text = _read(_TERRAFORM)
    assert 'edge_config_dir = "${path.module}/../compose/edge"' in text
    assert "mkdir -p '${var.app_path}/edge'" in text
    edge_list = text.split("edge_files      = [")[1].split("]")[0]
    for name in _EDGE_FILES:
        assert f'source      = "${{local.edge_config_dir}}/{name}"' in text
        assert f'destination = "${{var.app_path}}/edge/{name}"' in text
        assert f'"{name}"' in edge_list
        assert (_REPO / "deploy" / "compose" / "edge" / name).is_file()
    # A changed edge file triggers a rollout.
    assert 'filesha256("${local.edge_config_dir}/${name}")' in text


def test_terraform_writes_compose_profiles() -> None:
    text = _read(_TERRAFORM)
    assert "COMPOSE_PROFILES=${var.compose_profiles}" in text
    assert '%{if var.compose_profiles != ""~}' in text
    assert "compose_profiles = var.compose_profiles" in text
    variables = _read(_VARIABLES)
    block = variables.split('variable "compose_profiles"')[1].split("\n}")[0]
    assert "type        = string" in block and 'default     = ""' in block


def test_release_sets_compose_profiles_per_environment() -> None:
    text = _read(_RELEASE)
    staging = text.split("- name: Deploy staging with Terraform")[1].split("- name:")[0]
    production = text.split("- name: Deploy production with Terraform")[1].split("- name:")[0]
    assert "TF_VAR_compose_profiles: graph\n" in staging
    assert "TF_VAR_compose_profiles: analytics\n" in production
    assert text.count("TF_VAR_compose_profiles") == 2


def test_health_checks_run_inside_the_api_container() -> None:
    remote = _read(_REMOTE_SCRIPT)
    assert "curl" not in remote
    for path in ("/api/v1/health", "/api/v1/ready"):
        assert re.search(
            rf"docker compose -f '\$compose_file' exec -T api python -c .*{path}", remote
        )
    terraform = _read(_TERRAFORM)
    assert "curl" not in terraform
    assert "exec -T api python -c" in terraform


def test_remote_script_ships_edge_files_and_compose_profiles() -> None:
    remote = _read(_REMOTE_SCRIPT)
    assert f'edge_files="{" ".join(_EDGE_FILES)}"' in remote
    assert "mkdir -p '$DEPLOY_APP_PATH/edge'" in remote
    assert '$DEPLOY_APP_PATH/edge/"' in remote
    assert "COMPOSE_PROFILES=%s" in remote and "DEPLOY_COMPOSE_PROFILES+x" in remote
    assert "staging) printf 'COMPOSE_PROFILES=graph" in remote
    assert "production) printf 'COMPOSE_PROFILES=analytics" in remote


def test_compose_check_covers_edge_profiles_and_ports() -> None:
    text = _read(_CHECK_COMPOSE)
    assert 'cp "$repo_root"/deploy/compose/edge/* "$tmp_dir/deploy/compose/edge/"' in text
    for profile in ("graph", "analytics", "pooler", "redis-split"):
        assert f"--profile {profile}" in text
    assert "config --format json" in text
    assert 'name != "edge" or published not in ("80", "443")' in text


def _check_env(content: str, target: str = "production", **extra: str) -> tuple[int, str]:
    if shutil.which("sh") is None or shutil.which("awk") is None:
        pytest.skip("sh and awk are required")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "DEPLOY_ENV_FILE_CONTENT": content,
        **extra,
    }
    result = subprocess.run(
        ["sh", str(_CHECK_ENV), target],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.returncode, result.stderr + result.stdout


_PINNED = "\n".join(
    [
        "REDIS_PASSWORD=abc",
        "QDRANT_IMAGE=qdrant/qdrant:v1.12.0",
        "MINIO_IMAGE=minio/minio@sha256:" + "a" * 64,
        "RABBITMQ_IMAGE=rabbitmq:3.13-management",
    ]
)
_CADDY = "\nCADDY_IMAGE=caddy:2.10.2"


@pytest.mark.parametrize(
    ("content", "extra", "code", "message"),
    [
        (_PINNED, {}, 1, "CADDY_IMAGE is not set"),
        (_PINNED + "\nCADDY_IMAGE=caddy:latest", {}, 1, "CADDY_IMAGE uses :latest"),
        (_PINNED + _CADDY, {}, 0, "0 error(s)"),
        (
            _PINNED + _CADDY + "\nCOMPOSE_PROFILES=analytics,pooler",
            {},
            1,
            "PGBOUNCER_IMAGE is not set",
        ),
        (_PINNED + _CADDY, {"COMPOSE_PROFILES": "pooler"}, 1, "PGBOUNCER_IMAGE is not set"),
        (
            _PINNED + _CADDY + "\nPGBOUNCER_IMAGE=edoburu/pgbouncer",
            {},
            1,
            "PGBOUNCER_IMAGE has no tag or digest",
        ),
        (
            _PINNED + "\nCADDY_IMAGE=caddy\nPGBOUNCER_IMAGE=edoburu/pgbouncer:latest",
            {"DEPLOY_ALLOW_UNPINNED_IMAGES": "true"},
            0,
            "2 warning(s)",
        ),
    ],
)
def test_deploy_env_check_pins_edge_and_pooler_images(
    content: str, extra: dict[str, str], code: int, message: str
) -> None:
    returncode, output = _check_env(content, **extra)
    assert returncode == code, output
    assert message in output


def test_deploy_env_check_keeps_staging_as_warnings() -> None:
    returncode, output = _check_env(_PINNED, target="staging")
    assert returncode == 0
    assert "WARNING: CADDY_IMAGE is not set" in output
