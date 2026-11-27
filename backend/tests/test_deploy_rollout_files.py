"""Deploy paths ship the RabbitMQ configuration and stop the replaced worker (R06-03, R06-04).

Staging and production mount ``./rabbitmq/rabbitmq.conf`` and ``./rabbitmq/enabled_plugins``
next to the compose file; a deploy path that does not copy them leaves Docker to create
empty directories there and RabbitMQ does not start. The 0.6.0 pools replace the single
``worker`` service, which keeps running unless ``up`` removes orphans.
"""

from __future__ import annotations

import re
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
