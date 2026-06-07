# 17 - Connector Operations Runbook

## Purpose

This runbook covers the operational workflow for connector providers in staging
and production: setup, contract validation, rollout, health monitoring,
troubleshooting, rollback, reconnect, secret rotation, and provider outages.

## Rollout Controls

Connector execution is gated by two settings:

- `FEATURE_ENABLE_CONNECTORS`
- `CONNECTOR_ROLLOUT_STAGE`

Supported rollout stages:

- `off` - disable connector creation, refresh, disconnect, OAuth completion, and sync operations
- `development` - enable only in development deployments
- `staging` - enable only in staging deployments
- `production` - enable only in production deployments
- `all` - enable in every non-test deployment

If the rollout stage is `off`, the runtime treats the connector platform as
disabled even if the feature flag is still set to true.

## Health and Observability

Use the admin health endpoint to inspect connector status:

- `GET /api/v1/admin/connectors/health`

The response includes:

- organization scope
- generated range
- overall connector platform status
- per-provider connection, sync, retry, skip, ingestion, and citation counts
- average latency and top error codes

Provider-specific signals are derived from:

- sync run lifecycle data
- connector audit events
- document and citation provenance
- structured connector logs

## New Provider Checklist

Before merging a new provider:

1. Register the provider in the shared provider registry.
2. Implement the adapter and normalizer behind the shared connector contract.
3. Add provider fixtures and contract tests using the shared harness.
4. Verify sync, delta, download, and ingestion behavior against the fake provider.
5. Document provider-specific setup and limitations in the connector platform docs.
6. Add the provider to the connector contract CI job if it is meant to ship with the default bundle.

## Rollout Checklist

Use this sequence for a new provider or a major connector change:

1. Merge adapter and contract test coverage.
2. Deploy to development with the connector platform enabled.
3. Confirm `/api/v1/admin/connectors/health` shows healthy or expected degraded signals.
4. Roll out to staging with the feature flag enabled and the rollout stage pinned to `staging`.
5. Validate reconnect, refresh, and sync failure handling under a staging dataset.
6. Promote to production by moving `CONNECTOR_ROLLOUT_STAGE` to `production`.
7. Leave the feature flag on and roll back by moving the stage back to `off` if needed.

## Troubleshooting

### No provider appears in the UI

- Confirm the provider registration exists in the shared registry.
- Check that the connector platform rollout is enabled for the deployment.
- Verify the backend logs include the provider key and connection identifier.

### Sync runs are failing

- Check `/api/v1/admin/connectors/health` for provider-specific error codes.
- Inspect the connector sync run and audit logs for rate limits, skipped items,
  ingestion failures, and OAuth refresh failures.
- Verify the provider credential is still valid and scoped correctly.

### OAuth reconnect fails

- Confirm the redirect URI matches the provider configuration.
- Verify the stored OAuth state has not expired.
- Re-run the OAuth connect flow after clearing the existing connection if the
  provider has rotated scopes or changed consent requirements.

### Secret rotation

- Rotate `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` through the secret manager.
- Update `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID` when the active key changes.
- Reconnect any credentials that cannot be decrypted after the rotation.

### Provider outage

- Use the health endpoint to confirm whether the issue is provider-wide.
- Keep the connector platform enabled only if you need to preserve reads or
  inspect existing state.
- Pause or disable sync jobs for the affected provider if repeated retries are
  causing noise or downstream load.

## Rollback

Rollback should be configuration-first:

1. Set `CONNECTOR_ROLLOUT_STAGE=off`.
2. Keep the feature flag on if you need to inspect the existing data model and
   health signals.
3. Disable or pause sync jobs for the affected provider.
4. Reconnect only after the provider issue or adapter regression is resolved.

If the issue is a provider-specific regression, revert the provider adapter and
rerun the contract suite before re-enabling the rollout stage.
