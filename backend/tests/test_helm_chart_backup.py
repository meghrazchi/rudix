"""Helm chart backup CronJobs (0.8.0, A2, R08-06): one per kind, key from a Secret file."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.helm_support import (
    CHART_DIR,
    all_values_files,
    assert_common_invariants,
    containers,
    pod_specs,
    render_chart,
    render_failure,
    values_file,
)

ALL_FEATURES = values_file("ci/all-features-values.yaml")
ENABLED = {
    "backup.enabled": "true",
    "backup.bucket": "rudix-backups",
    "backup.encryptionKeySecret.name": "rudix-backup-key",
}


def _cronjobs(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "CronJob"}


def _env(container: dict[str, Any]) -> dict[str, Any]:
    return {item["name"]: item for item in container.get("env") or []}


@pytest.mark.parametrize("path", all_values_files(), ids=lambda path: path.rsplit("/", 1)[-1])
def test_every_values_file_renders(path: str) -> None:
    objects = render_chart([path])
    assert_common_invariants(objects)
    expected = ["rudix-backup-objects", "rudix-backup-postgres", "rudix-backup-qdrant"]
    assert sorted(_cronjobs(objects)) == (expected if path == ALL_FEATURES else [])


def test_backups_are_off_by_default() -> None:
    assert _cronjobs(render_chart()) == {}
    values = yaml.safe_load((CHART_DIR / "values.yaml").read_text())
    assert values["backup"]["enabled"] is False
    assert values["backup"]["postgres"]["enabled"] is False  # managed PITR is primary
    assert values["backup"]["concurrencyPolicy"] == "Forbid"


def test_enabled_without_postgres_renders_qdrant_and_objects() -> None:
    objects = render_chart([], ENABLED)
    assert_common_invariants(objects)
    assert sorted(_cronjobs(objects)) == ["rudix-backup-objects", "rudix-backup-qdrant"]


def test_all_features_cronjobs() -> None:
    objects = render_chart([ALL_FEATURES])
    jobs = _cronjobs(objects)
    for kind in ("postgres", "qdrant", "objects"):
        job = jobs[f"rudix-backup-{kind}"]
        spec = job["spec"]
        assert job["metadata"]["labels"]["app.kubernetes.io/component"] == f"backup-{kind}"
        assert spec["concurrencyPolicy"] == "Forbid"
        assert spec["timeZone"] == "Etc/UTC"
        assert spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 21600
        assert spec["jobTemplate"]["spec"]["backoffLimit"] == 1
        (pod,) = pod_specs(job)
        assert pod["restartPolicy"] == "Never"
        assert pod["automountServiceAccountToken"] is False
        main = pod["containers"][0]
        assert main["image"] == "registry.invalid/rudix/worker:ci-check"
        assert main["command"] == ["python", "scripts/backup_run.py", "--kind", kind]
        env = _env(main)
        assert env["BACKUP_ENCRYPTION_KEY_FILE"]["value"] == "/run/secrets/rudix-backup/backup.key"
        assert env["BACKUP_BUCKET"]["value"] == "rudix-ci-backups"
        assert env["BACKUP_PREFIX"]["value"] == "rudix-ci"
        assert env["BACKUP_ENABLED"]["value"] == "true"
        mounts = {mount["name"]: mount for mount in main["volumeMounts"]}
        assert mounts["backup-key"] == {
            "name": "backup-key",
            "mountPath": "/run/secrets/rudix-backup",
            "readOnly": True,
        }
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        assert volumes["backup-key"]["secret"]["secretName"] == "rudix-ci-backup-key"
        assert volumes["backup-key"]["secret"]["items"] == [
            {"key": "backup.key", "path": "backup.key"}
        ]
        assert volumes["backup-work"]["emptyDir"]["sizeLimit"] == "50Gi"
        for container in containers(job):
            security = container["securityContext"]
            assert security["readOnlyRootFilesystem"] is True
            assert security["allowPrivilegeEscalation"] is False


def test_postgres_dump_runs_in_the_postgres_image_init_container() -> None:
    job = _cronjobs(render_chart([ALL_FEATURES]))["rudix-backup-postgres"]
    (pod,) = pod_specs(job)
    (init,) = pod["initContainers"]
    digest = "sha256:" + "0" * 63 + "3"
    assert init["image"] == f"postgres@{digest}"
    assert "pg_dump -Fc" in init["command"][-1]
    url = _env(init)["BACKUP_DATABASE_URL"]
    assert url["valueFrom"]["secretKeyRef"] == {
        "name": "rudix-ci-app-env",
        "key": "BACKUP_DATABASE_URL",
    }
    assert {mount["name"] for mount in init["volumeMounts"]} == {"tmp", "backup-work"}
    for other in ("rudix-backup-qdrant", "rudix-backup-objects"):
        assert "initContainers" not in pod_specs(_cronjobs(render_chart([ALL_FEATURES]))[other])[0]


def test_postgres_image_tag_without_digest() -> None:
    values = {**ENABLED, "backup.postgres.enabled": "true", "secrets.existingSecret": "env"}
    job = _cronjobs(render_chart([], values))["rudix-backup-postgres"]
    assert pod_specs(job)[0]["initContainers"][0]["image"] == "postgres:16"


def test_the_key_never_reaches_env_or_config() -> None:
    objects = render_chart([ALL_FEATURES])
    for obj in objects:
        if obj["kind"] == "ConfigMap":
            assert not any(
                "ENCRYPTION_KEY" in key and not key.endswith("_FILE") for key in obj["data"]
            )
        for container in containers(obj):
            for item in container.get("env") or []:
                assert item["name"] != "BACKUP_ENCRYPTION_KEY"
    assert not [obj for obj in objects if obj["kind"] == "Secret"]


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        ({"backup.enabled": "true"}, "backup.encryptionKeySecret.name is required"),
        (
            {"backup.enabled": "true", "backup.encryptionKeySecret.name": "k"},
            "backup.bucket is required",
        ),
        ({**ENABLED, "backup.encryptionKeySecret.key": ""}, "encryptionKeySecret.key is required"),
        ({**ENABLED, "backup.concurrencyPolicy": "Allow"}, "concurrencyPolicy must be Forbid"),
        ({**ENABLED, "backup.postgres.enabled": "true"}, "needs secrets.existingSecret"),
        (
            {
                **ENABLED,
                "backup.postgres.enabled": "true",
                "secrets.existingSecret": "env",
                "backup.postgres.image.digest": "sha256:short",
            },
            "backup.postgres.image.digest must be",
        ),
    ],
)
def test_invalid_backup_values_fail(set_values: dict[str, str], message: str) -> None:
    assert message in render_failure([], set_values)


FRESHNESS = "config.env.BACKUP_FRESHNESS_CHECK_ENABLED"


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        ({FRESHNESS: "true"}, "needs config.env.BACKUP_BUCKET"),
        (
            {**ENABLED, FRESHNESS: "true", "config.env.BACKUP_BUCKET": "other-bucket"},
            "must equal backup.bucket and backup.prefix",
        ),
        (
            {
                **ENABLED,
                FRESHNESS: "true",
                "config.env.BACKUP_BUCKET": "rudix-backups",
                "config.env.BACKUP_PREFIX": "elsewhere",
            },
            "must equal backup.bucket and backup.prefix",
        ),
    ],
)
def test_freshness_check_needs_the_same_bucket_in_config(
    set_values: dict[str, str], message: str
) -> None:
    # The beat task runs in the worker pods, which never see the CronJob-only bucket env.
    assert message in render_failure([], set_values)


def test_freshness_check_renders_with_matching_config() -> None:
    objects = render_chart(
        [], {**ENABLED, FRESHNESS: "true", "config.env.BACKUP_BUCKET": "rudix-backups"}
    )
    config = next(obj for obj in objects if obj["kind"] == "ConfigMap")
    assert config["data"]["BACKUP_BUCKET"] == "rudix-backups"
    assert render_chart([], {FRESHNESS: "false"})


def test_data_stores_key_is_documentation_only() -> None:
    values = yaml.safe_load((CHART_DIR / "values.yaml").read_text())["dataStores"]
    assert values["qdrant"]["replicationFactor"] >= 2
    assert values["rabbitmq"]["nodes"] == 3 and values["rabbitmq"]["queueType"] == "classic"
    assert values["objectStorage"]["versioning"] is True
    default = render_chart()
    changed = render_chart([], {"dataStores.qdrant.replicationFactor": "5"})
    strip = [
        {k: v for k, v in obj.items() if k != "metadata"} for obj in default
    ]  # annotations hash only the ConfigMap
    assert strip == [{k: v for k, v in obj.items() if k != "metadata"} for obj in changed]
