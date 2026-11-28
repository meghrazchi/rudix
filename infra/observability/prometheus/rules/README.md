# Prometheus rule files (0.8.0)

Prometheus loads every `*.yml` file in this directory (`rule_files` entry
`/etc/prometheus/rules/*.yml` in `../prometheus.yml`; the observability Compose stack mounts
`../` at `/etc/prometheus`). `../alerts.yml` keeps the alerts that existed before 0.8.0.

One owner per file. A task edits only its own file:

| File | Owner | Content |
|---|---|---|
| `backups.yml` | A2 | Backup freshness alerts from `rudix_backup_last_success_timestamp_seconds` |
| `slo-recording.yml` | B2 | SLO recording rules from `infra/observability/slo_targets.yml` |
| `slo-burn-rate.yml` | B2 | Multi-window burn-rate alerts on the recorded SLO series |
| `beat.yml` | B2 | Celery beat heartbeat alert from `rudix_beat_heartbeat_timestamp_seconds` |
| `database.yml` | C2 | Read replica lag alert from `rudix_db_replica_lag_seconds` |

Every file must pass `backend/tests/test_prometheus_rules.py`:

- each `rudix_*` series in an `expr` is exported by the application registry
  (`app.core.metrics.registry`, suffixes `_bucket`, `_sum`, `_count`, `_total`, `_created`
  resolved) or is recorded by a rule in this directory or `alerts.yml`;
- each alert has `labels.severity` and `annotations.summary`;
- no alert or record name repeats across files.

`promtool check rules` and the unit tests in `../tests/*.yml` (`promtool test rules`) run in
CI (job `deploy-config`, step "Check Prometheus rules"); they are not run on a development
machine. The B2 files are derived from `../../slo_targets.yml`;
`backend/tests/test_slo_rules.py` checks that they agree.
