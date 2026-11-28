# DR: credential compromise

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); not yet exercised in a drill
- `Last Updated`: 2026-11-28
- `Related Docs`: [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md)
  "Secrets" and its "Rotation" subsection (per-secret rotation steps, added in `0.8.0` by
  D1), [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md) "Rotate the backup key",
  [../SECURITY.md](../SECURITY.md)

Scope: a secret, key, or token may be known to someone who should not have it: committed to
git, pasted in a ticket or chat, printed in a log, found by the secret scanner, present on a
lost laptop or a compromised CI runner, or held by a person who left. Treat "may be exposed"
as exposed.

## Detection

- `.github/workflows/secret-scan.yml` (gitleaks) reports a finding on a push or pull request.
- A provider (OpenAI, the cloud, GitHub) sends a leaked-key notice or shows unexpected usage
  or cost (`rudix_llm_*` cost metrics, the usage dashboard).
- Audit logs show unexpected admin actions, API key or service account use from new IPs
  (`last_used_ip`), sign-ins at odd times, or new webhooks.
- Authentication failure spikes, rate-limit spikes on one credential, or `401`s after a
  rotation someone else made.
- A person reports having shared or lost a credential.

## Decision owner

- Security lead: owns the incident, decides scope, the order of rotation, and whether
  sessions are revoked for everyone.
- Incident commander: coordinates the deploys and customer communication.
- Platform owner: rotates infrastructure secrets (cloud, database, broker, registry, SSH,
  Terraform state, backup bucket).
- Data protection lead: decides on notification duties if customer data may have been read.
- Never record secret values in the incident record; name the secret and where it lives.

## Steps

1. Scope. Write down, for each suspected secret: its name, where it is stored (GitHub secret
   `*_ENV_FILE`, Kubernetes Secret, secret manager, host file), what it grants, and since when
   it may be exposed. Use this inventory:

   | Secret | Grants | Revoke or rotate |
   |---|---|---|
   | `APP_AUTH_SECRET` | Signing of every session and access token | Rotate; every user signs in again (with D1's `APP_AUTH_SECRET_PREVIOUS`, verify-only overlap) |
   | Database passwords (`rudix_app`, `rudix_maintenance`, migration owner) | Read and write all tenant data | `ALTER ROLE ... PASSWORD` from the secret store, update the URLs, redeploy |
   | `OPENAI_API_KEY` and other provider keys | Model usage billed to Rudix | Revoke in the provider console, create a new key |
   | `MINIO_*` / object storage keys | Every uploaded document | Rotate the access key; check bucket access logs |
   | `QDRANT_API_KEY`, `REDIS_PASSWORD`, RabbitMQ users, `NEO4J_PASSWORD` | Vectors and payload snippets, rate-limit and session state, task queues, the graph | Rotate on the store, update URLs, restart clients |
   | `METRICS_BEARER_TOKEN` | Metrics (no tenant data, but operational detail) | Rotate; update the Prometheus token file |
   | Customer API keys (`rudix_...`), service account tokens (`svc_...`) | One organisation's API | Revoke or rotate in the admin UI (customers can do it themselves) |
   | Webhook signing secrets (`whsec_...`), bot tokens, SSO and SCIM tokens | Forged events, bot impersonation, provisioning | Rotate per integration in the admin UI and at the provider |
   | `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` | Decrypts stored connector credentials | Rotation needs re-encryption (deferred, not built): revoke each connector's credentials at the provider and reconnect |
   | Backup encryption key and backup bucket credentials | Every backup | [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md) "Rotate the backup key"; rotate bucket keys |
   | Deploy SSH key, `GHCR_TOKEN`, Terraform state keys, cloud credentials | Hosts, images, infrastructure | Remove the key from `authorized_keys`, revoke tokens, rotate in GitHub secrets |
   | `SENTRY_DSN`, Langfuse keys | Error and trace ingestion (may include metadata) | Rotate in the service |

2. Contain, in order of blast radius (infrastructure and signing keys first):
   - Revoke what can be revoked immediately (provider keys, API keys, tokens, SSH keys).
   - If `APP_AUTH_SECRET` or a database password is affected, plan a short maintenance
     window: rotation logs every user out or restarts every service.
   - If the exposure came from a compromised CI runner or laptop, disable that runner or
     the person's access first.
3. Rotate. Follow docs/11 "Secrets" "Rotation" for the per-secret procedure. General shape:
   1. Generate the new value in the secret store (never in a shell history or a ticket).
   2. Update the store or provider first when it supports two valid credentials at once
      (database roles, object storage keys, provider keys); otherwise schedule the switch.
   3. Update the GitHub environment secret (`STAGING_ENV_FILE`, `PRODUCTION_ENV_FILE`) or the
      Kubernetes Secret, and redeploy through the release workflow (or `kubectl rollout restart`
      for a Secret change).
   4. Revoke the old value once every service uses the new one.
4. Remove the exposure: delete the ticket or chat message, ask the platform to purge it, and
   for a git commit rotate first (a history rewrite does not un-leak a pushed secret, docs/11).
   Do not add the value to the secret-scan allowlist.
5. Investigate use: audit logs (`audit_logs`, authorization decision logs), provider usage,
   object storage and backup bucket access logs, and database connection logs for the
   exposure window. Record findings without copying data.
6. Decide on notification with the data protection lead when tenant data may have been read.
7. Write the post-incident review: cause, timeline, what was rotated, and the follow-up that
   prevents a repeat.

## Verification

- The old credential no longer works (try it once, from an isolated machine, without
  printing it).
- `/api/v1/ready` reports every dependency up after the redeploy; sign-in, an upload, and a
  chat with citations work.
- No new use of the old credential appears in provider or audit logs after revocation.
- The secret scanner is clean on the default branch; the rotation is recorded in the secret
  store's history.
- For the backup key: a fresh backup of each kind exists with the new key and an old backup
  still restores with the retained old key.
