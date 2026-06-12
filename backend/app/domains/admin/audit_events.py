"""Structured audit-log action constants for F225 provider governance.

All constants follow the pattern: domain.resource.event
Callers pass these as the `action` argument to AuditLogService.record().
"""

# Provider configuration
PROVIDER_CONFIG_CHANGED = "admin.model_provider.config.changed"
PROVIDER_CONFIG_RESET = "admin.model_provider.config.reset"

# Provider test-connection probe
PROVIDER_TEST_CONNECTION = "admin.model_provider.test_connection.executed"

# Runtime routing events (written at request time, not admin-time)
PROVIDER_FALLBACK_USED = "model_provider.fallback.used"
PROVIDER_POLICY_BLOCKED = "model_provider.request.policy_blocked"

# Model profile lifecycle
MODEL_PROFILE_UPSERTED = "admin.model_profile.upserted"
MODEL_PROFILE_DELETED = "admin.model_profile.deleted"

# Evaluation / agent runs that use experimental providers
EVALUATION_RUN_EXPERIMENTAL_PROVIDER = "evaluation.run.experimental_provider"
AGENT_RUN_EXPERIMENTAL_PROVIDER = "agent.run.experimental_provider"

# Governance policy changes
PROVIDER_GOVERNANCE_POLICY_UPDATED = "admin.governance.provider_policy.updated"

# Feature flag overrides (F159)
FEATURE_FLAG_OVERRIDE_SET = "admin.feature_flag.override.set"
FEATURE_FLAG_OVERRIDE_CLEARED = "admin.feature_flag.override.cleared"
