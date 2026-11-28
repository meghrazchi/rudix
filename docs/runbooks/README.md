# Runbooks

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); no scenario has been exercised in a drill yet
- `Last Updated`: 2026-11-28
- `Related Docs`: [../10_DEPLOYMENT_DOCKER.md](../10_DEPLOYMENT_DOCKER.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [../12_EVALUATION_AND_MONITORING.md](../12_EVALUATION_AND_MONITORING.md),
  [../27_INGESTION_AND_WORKERS_RUNBOOK.md](../27_INGESTION_AND_WORKERS_RUNBOOK.md),
  [../28_KUBERNETES_HELM_DEPLOYMENT.md](../28_KUBERNETES_HELM_DEPLOYMENT.md)

## Index

| Runbook | Use it when |
|---|---|
| [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md) | Setting up backups, a backup alert fires, a restore is needed, or the backup key rotates |
| [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md) | Recording a restore drill (RPO, RTO, findings) |
| [DR_HOST_OR_REGION_LOSS.md](./DR_HOST_OR_REGION_LOSS.md) | The Compose host, a cluster, or a whole region is gone |
| [DR_DATABASE_CORRUPTION.md](./DR_DATABASE_CORRUPTION.md) | PostgreSQL data is wrong, deleted, or unreadable |
| [DR_VECTOR_INDEX_LOSS.md](./DR_VECTOR_INDEX_LOSS.md) | Qdrant collections are lost or corrupted |
| [DR_BROKER_LOSS.md](./DR_BROKER_LOSS.md) | RabbitMQ is down or its queues are lost |
| [DR_CREDENTIAL_COMPROMISE.md](./DR_CREDENTIAL_COMPROMISE.md) | A secret, key, or token may be exposed |

Related procedures that already exist elsewhere: worker pools, the outbox, the document
reaper, the dead-letter queue, the quorum cut-over, and the vector index alias swap are in
[docs/27](../27_INGESTION_AND_WORKERS_RUNBOOK.md); rollback of a release is in
[docs/14](../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md).

## Format

Every scenario runbook has the same four sections, in this order:

1. **Detection**: the alerts, metrics, logs, or symptoms that start it, with their names.
2. **Decision owner**: the roles that decide and approve (never a person's name), and who is
   informed. Roles used here:
   - *On-call engineer*: first responder, runs the steps.
   - *Incident commander*: owns the incident, decides on failover, restore, and customer
     communication; any senior engineer on the rota.
   - *Platform owner*: owns the infrastructure accounts (cloud, DNS, registry, backup bucket).
   - *Security lead*: owns credential and data-exposure decisions.
   - *Data protection lead*: decides on notification duties when personal data is affected.
3. **Steps**: numbered, copy-pasteable where possible, with the decision points marked.
4. **Verification**: how to prove the service is back and no data is missing.

Rules for every runbook:

- No measured figure (RPO, RTO, latency, duration) is written down until a drill or an
  incident measured it; measured values go in [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md).
- Never paste secrets, URLs with credentials, document text, or customer data into a runbook,
  a ticket, or a chat channel. Name the secret, not its value.
- Restored data is production data: restore only into stores with production access
  controls and remove scratch copies after use.
- Keep each runbook under 500 lines; link to the detailed docs instead of copying them.
- Update the runbook in the same change as the behaviour it describes.
