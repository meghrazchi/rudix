# Authorization System

> **F336** — Authorization regression suite, tenant-isolation tests, documentation, and rollout plan.  
> Built on top of F330 (policy engine), F331 (schema), F332 (enforcement), F333 (effective-permissions API), F334 (admin UI), and F335 (conflict detection).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Role Matrix](#2-role-matrix)
3. [Feature Permissions Reference](#3-feature-permissions-reference)
4. [Resource Grants and Denies](#4-resource-grants-and-denies)
5. [Conflict Rules Catalog](#5-conflict-rules-catalog)
6. [Future Source Adapter Contract](#6-future-source-adapter-contract)
7. [Admin Operations Guide](#7-admin-operations-guide)
8. [Rollout Plan](#8-rollout-plan)
9. [Monitoring and Observability](#9-monitoring-and-observability)
10. [Rollback Procedure](#10-rollback-procedure)
11. [Database Row-Level Security](#11-database-row-level-security)

---

## 1. Overview

Rudix uses a **stateless, 11-rule policy engine** (`PolicyEngine`) that evaluates every authorization request through an ordered precedence chain. All enforcement is on the backend; frontend permission checks (via `useEffectivePermissions` / `PermissionGate`) are UX helpers only.

### Design Principles

- **Backend is the source of truth.** Frontend checks are never a substitute for backend enforcement.
- **Owner and admin bypass all resource-level checks** (rule 5: `owner_admin_override`) unless a system deny applies.
- **Unknown future resource types default to deny** until a `SourceAuthorizationAdapter` is registered.
- **Tenant boundary is inviolable.** A principal in org A can never access org B resources, even with an explicit grant, ACL entry, or collection membership that references the same resource ID.
- **No sensitive fields in authorization responses.** API keys, provider tokens, raw credentials, document text, and chunk content must never appear in authorization decisions, conflict records, or explain-decision traces.

### The 11-Rule Precedence Chain

```
 1  no_organization_context   → deny  (principal has no org context at all)
 2  tenant_boundary           → deny  (resource belongs to a different org)
 3  system_deny               → deny  (built-in system resource, always blocked)
 4  unknown_resource_type     → deny  (unregistered future source type)
 5  owner_admin_override      → allow (owner/admin bypass all resource checks)
 6  explicit_resource_deny    → deny  (admin-created explicit deny on this subject)
 7  explicit_resource_allow   → allow (admin-created explicit grant on this subject)
 8  collection_allow          → allow (document is in a collection accessible to subject)
 9  connector_acl             → allow/deny (document has a connector; subject must be in ACL)
10  feature_entitlement       → deny  (feature gate is off for this resource)
11  role_permission           → allow/deny (base role permission check — last resort)
```

---

## 2. Role Matrix

### Built-in Roles

| Role              | Inherits | Description                                              |
|-------------------|----------|----------------------------------------------------------|
| `owner`           | —        | Full access; implicit admin on everything except system denies |
| `admin`           | —        | Full access; same as owner for resource policy purposes  |
| `member`          | —        | Standard user; view/upload docs, use chat, list collections |
| `viewer`          | —        | Read-only; view docs and collections, use basic chat     |
| `reviewer`        | —        | Can evaluate; view docs, run and view evaluations        |
| `developer`       | —        | Extended API access; view docs, limited admin reads      |
| `billing_admin`   | —        | Billing-only; cannot view any documents or collections   |
| `security_admin`  | —        | Security center access; cannot view documents or collections |

### Permission Grants per Role

| Permission                    | owner | admin | member | viewer | reviewer | developer | billing_admin | security_admin |
|-------------------------------|:-----:|:-----:|:------:|:------:|:--------:|:---------:|:-------------:|:--------------:|
| `documents:view`              | ✓     | ✓     | ✓      | ✓      | ✓        | ✓         | —             | —              |
| `documents:upload`            | ✓     | ✓     | ✓      | —      | —        | ✓         | —             | —              |
| `documents:delete`            | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `documents:manage`            | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `collections:view`            | ✓     | ✓     | ✓      | ✓      | ✓        | ✓         | —             | —              |
| `collections:create`          | ✓     | ✓     | ✓      | —      | —        | ✓         | —             | —              |
| `collections:manage`          | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `collections:delete`          | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `chat:use`                    | ✓     | ✓     | ✓      | ✓      | ✓        | ✓         | —             | —              |
| `chat:use_collections`        | ✓     | ✓     | ✓      | —      | —        | ✓         | —             | —              |
| `chat:manage_sessions`        | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `evaluations:view`            | ✓     | ✓     | —      | —      | ✓        | ✓         | —             | —              |
| `evaluations:create`          | ✓     | ✓     | —      | —      | —        | ✓         | —             | —              |
| `evaluations:manage`          | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `evaluations:run`             | ✓     | ✓     | —      | —      | ✓        | ✓         | —             | —              |
| `admin:access`                | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `audit:view`                  | ✓     | ✓     | —      | —      | —        | —         | —             | ✓              |
| `security_center:view`        | ✓     | ✓     | —      | —      | —        | —         | —             | ✓              |
| `security_center:configure`   | ✓     | ✓     | —      | —      | —        | —         | —             | ✓              |
| `billing:manage`              | ✓     | —     | —      | —      | —        | —         | ✓             | —              |
| `api_keys:manage`             | ✓     | ✓     | —      | —      | —        | ✓         | —             | —              |
| `webhooks:manage`             | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `agents:use`                  | ✓     | ✓     | ✓      | —      | —        | ✓         | —             | —              |
| `mcp:manage`                  | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `roles:manage`                | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `team:manage`                 | ✓     | ✓     | —      | —      | —        | —         | —             | —              |
| `graph:view`                  | ✓     | ✓     | ✓      | ✓      | ✓        | ✓         | —             | —              |
| `graph:manage`                | ✓     | ✓     | —      | —      | —        | —         | —             | —              |

---

## 3. Feature Permissions Reference

The `feature_entitlement` rule (rule 10) blocks access when `ResourceContext.feature_enabled` is `False`. This is determined by the org's feature flag state. Feature flags that gate resource types:

| Feature Flag                       | Setting Attribute                             | Gated Resource / Feature           |
|------------------------------------|-----------------------------------------------|------------------------------------|
| `agents`                           | `feature_enable_agents`                       | Agentic workflows                  |
| `authorization_enforcement`        | `feature_enable_authorization_enforcement`    | **Enforcement strict mode** (F336) |
| `connectors`                       | `feature_enable_connectors`                   | Connector sources                  |
| `evaluations`                      | `feature_enable_evaluations`                  | Evaluation runs and datasets       |
| `graph_rag`                        | `feature_enable_graph_rag`                    | GraphRAG retrieval path            |
| `graph_extraction`                 | `feature_enable_graph_extraction`             | Entity extraction pipeline         |
| `graph_explorer`                   | `feature_enable_graph_explorer`               | Graph explorer UI                  |
| `mcp`                              | `feature_enable_mcp`                          | MCP server integration             |
| `query_rewriting`                  | `feature_enable_query_rewriting`              | Query decomposition                |
| `language_aware_rag`               | `feature_enable_language_aware_rag`           | Multilingual RAG answers           |
| `advanced_pdf_extraction`          | `feature_enable_advanced_pdf_extraction`      | Structured PDF block extraction    |
| `chunking_profiles`                | `feature_enable_chunking_profiles`            | Custom chunking profiles           |
| `adaptive_chunking`                | `feature_enable_adaptive_chunking`            | Adaptive chunking strategy         |
| `provider_fallback`                | `feature_enable_provider_fallback`            | LLM provider fallback chain        |
| `local_llm_profiles`               | `feature_enable_local_llm_profiles`           | Local LLM provider profiles        |

> **Important:** `owner` and `admin` bypass the feature entitlement gate (rule 5 fires before rule 10). Feature flags block non-admin users only.

---

## 4. Resource Grants and Denies

Admins can create per-subject, per-resource, per-action access overrides via the Admin > Permissions > Grants/Denies tabs (backed by `GET/POST/DELETE /admin/permissions/grants` and `/admin/permissions/denies`).

### Grant Semantics

- A **grant** fires at rule 7 (`explicit_resource_allow`) and allows a specific subject (user or role) access to a specific resource+action, bypassing role and collection rules.
- Grants cannot bypass rule 6 (`explicit_resource_deny`). A deny always wins.
- Grants cannot bypass rules 1–5 (org context, tenant boundary, system deny, unknown type, owner/admin override).

### Deny Semantics

- A **deny** fires at rule 6 (`explicit_resource_deny`) and blocks a specific subject from a specific resource+action, even if they would otherwise be allowed by role or collection membership.
- Denies cannot block owner or admin (rule 5 fires first).

### Common Use Cases

| Scenario                                        | Solution                                                    |
|-------------------------------------------------|-------------------------------------------------------------|
| Give a viewer edit access to one document       | Create a grant: subject=viewer, resource=document, action=manage |
| Block a member from one sensitive collection    | Create a deny: subject=member, resource=collection, action=view |
| Give an external API key access to chat only   | Create API key with `chat:use` scope + grant on resource     |
| Remove access for one member from connector    | Create a deny on connector_source_item for that member      |

### Citation Checks on Every Chat Transport

The `cite` check runs on both `POST /chat` and the `/chat/ws` WebSocket pipeline through
`filter_chunks_by_cite_access` in `backend/app/application/chat/citation_access.py`. After the
source-provenance filter, every retrieved chunk whose document the user may not cite is dropped
before the prompt is built, so it cannot appear as a citation. A deny with action `cite` on a
document therefore removes that document from answers on both transports. Chunks whose document
cannot be found in the organization are also dropped. Scope-inventory answers apply the same check on both transports: a readable document is still listed, but it gets no citation unless the user may cite it. Owners and admins bypass the check (rule 5).

---

## 5. Conflict Rules Catalog

The `ConflictDetectionService.scan()` (POST `/admin/permissions/conflicts/scan`) detects the following conflict types:

| Conflict Type                         | Severity  | Description                                                               | Remediation                                                            |
|---------------------------------------|-----------|---------------------------------------------------------------------------|------------------------------------------------------------------------|
| `role_allow_resource_deny`            | blocking  | Subject has a role-based allow AND an explicit deny on the same resource  | Remove the deny if access should be granted, or review the role assignment |
| `collection_allow_connector_acl_deny` | warning   | Collection grants access but connector ACL blocks the source item         | Update connector ACL to include the subject, or remove from collection |
| `citation_visible_source_hidden`      | security_risk | Citation is accessible but its source document is not                 | Grant access to the source document or remove the citation grant        |
| `graph_entity_visible_evidence_inaccessible` | warning | Graph entity is visible but its evidence documents are not        | Grant access to evidence documents or restrict the entity               |
| `stale_grant_deleted_resource`        | info      | Grant references a document that no longer exists                         | Delete the stale grant to keep ACL records clean                       |
| `stale_grant_removed_connector`       | warning   | Grant references a connector that was deleted or deactivated              | Delete the stale grant to avoid confusion                              |
| `orphaned_acl_mapping`                | info      | SourceAclMapping references a connector that no longer exists             | Clean up the ACL mapping row                                           |
| `feature_deny_active_grant`           | warning   | An explicit grant exists but the feature is disabled for the org          | Enable the feature flag or remove the inactive grant                   |
| `explicit_grant_conflicts_role_deny`  | blocking  | Explicit grant and role-based deny exist for same subject+resource+action | Resolve the conflict by either adjusting the role or removing the grant |

### Conflict Severity Mapping

| API Severity    | DB Severity | Meaning                                                      |
|-----------------|-------------|--------------------------------------------------------------|
| `info`          | `low`       | No access impact, housekeeping only                          |
| `warning`       | `medium`    | Potential access inconsistency, should review                |
| `blocking`      | `high`      | Access grant and deny conflict; access outcome is undefined  |
| `security_risk` | `critical`  | Data leakage risk; immediate review required                 |

---

## 6. Future Source Adapter Contract

When a new data source is integrated (e.g., Notion, SharePoint, Slack), the connector must implement a `SourceAuthorizationAdapter` to enable per-item ACL enforcement. Without this, rule 9 (`connector_acl`) defaults to deny.

### Interface

```python
from abc import ABC, abstractmethod
from app.auth.policy_engine import SubjectContext, ResourceContext

class SourceAuthorizationAdapter(ABC):
    """Maps connector-specific ACL data into policy engine artifacts.
    
    Implementations must be registered via:
        SourceAuthorizationAdapterRegistry.register(connector_type, AdapterClass)
    """

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Unique identifier for this connector type (e.g. 'jira', 'google_drive')."""
        ...

    @abstractmethod
    async def resolve_item_acl(
        self,
        connector_id: str,
        external_item_id: str,
        subject: SubjectContext,
        db_session: AsyncSession,
    ) -> bool:
        """Return True if subject is allowed to access this connector item.
        
        Must check the connector's native ACL (e.g., Jira issue visibility,
        Drive file share permissions) for the subject's external identity.
        Never allow access if the subject cannot be mapped to an external identity.
        """
        ...

    @abstractmethod
    async def batch_filter_items(
        self,
        connector_id: str,
        external_item_ids: list[str],
        subject: SubjectContext,
        db_session: AsyncSession,
    ) -> frozenset[str]:
        """Return the subset of item IDs that the subject can access.
        
        Default implementations should call resolve_item_acl() per item.
        Override for batch efficiency if the upstream API supports it.
        """
        ...
```

### Registration

```python
# In your connector's __init__ or setup module:
from app.auth.policy_engine import SourceAuthorizationAdapterRegistry

SourceAuthorizationAdapterRegistry.register("notion", NotionAuthorizationAdapter)
```

### Deny-by-Default Guarantee

If no adapter is registered for a connector type:
- The `DefaultDenyAdapter` is returned from the registry.
- `resolve_item_acl()` always returns `False`.
- Rule 9 always denies unless the principal is owner/admin (bypassed by rule 5 first).

### Security Requirements for Adapters

1. **Never trust the external item ID alone** — verify the connector belongs to the same org.
2. **Map subjects to external identities** using a dedicated identity mapping table (not by email alone).
3. **Cache conservatively** — invalidate ACL cache on connector config changes, membership changes, and re-sync events.
4. **Log ACL resolution failures** via `log_authorization_event()` with `event="connector_acl_resolution_error"`.
5. **Never expose connector tokens or credentials** in authorization responses or log fields.

---

## 7. Admin Operations Guide

### Checking a User's Access

Use the **Access Debugger** tab in Admin > Permissions:
- Set `Subject User ID` to the target user's DB UUID.
- Set `Resource Type` (document, collection, connector, etc.).
- Set `Action` (view, create, delete, manage, chat, cite, sync, evaluate, export).
- Optionally set `Resource ID` for exact resource lookup.
- Click **Explain** to see the policy trace and matched rule.

Or via API:
```
GET /admin/permissions/explain-decision
  ?subject_user_id=<uuid>
  &resource_type=document
  &action=view
  &resource_id=<optional-uuid>
```
Requires: `security_center:view` permission.

### Viewing and Resolving Conflicts

```
GET  /admin/permissions/conflicts             # list all conflicts
GET  /admin/permissions/conflicts/{id}        # conflict detail + remediation
PATCH /admin/permissions/conflicts/{id}/status  # set investigating/resolved/dismissed
POST /admin/permissions/conflicts/scan        # trigger a fresh org-wide scan
```

Conflict scan is idempotent: running it multiple times will not create duplicate records for existing open/investigating conflicts. Dismissed and resolved conflicts can be re-detected on subsequent scans.

### Granting or Denying Access

```
POST /admin/permissions/grants    { subject_type, subject_value, resource_type, resource_id, action }
DELETE /admin/permissions/grants/{id}

POST /admin/permissions/denies    { subject_type, subject_value, resource_type, resource_id, action }
DELETE /admin/permissions/denies/{id}
```

Both endpoints require: `security_center:configure` permission.

### Changing the Authorization Enforcement Mode

The `authorization_enforcement` feature flag controls whether policy denials block requests (strict mode) or only log them (soft mode).

```
# Enable strict mode (default — recommended for production):
PUT /admin/feature-flags/authorization_enforcement
  Body: { "enabled": true, "reason": "Production deployment — all enforcement active." }

# Disable for canary rollout (log-only mode):
PUT /admin/feature-flags/authorization_enforcement
  Body: { "enabled": false, "reason": "Canary: monitoring deny events before enforcing." }
```

Requires: `admin:access` permission. All changes are audit-logged.

---

## 8. Rollout Plan

### Phase 0 — Pre-deployment Verification (Day -1)

- [ ] Run the full regression suite: `pytest -m authorization_regression -v`
- [ ] Run the isolation suite: `pytest -m isolation -v`
- [ ] Run the guardrails suite: `pytest -m guardrails -v`
- [ ] Verify all 4 authorization test files pass: `pytest tests/test_*_f336.py -v`
- [ ] Verify no test references `utcnow()` (deprecated; use `datetime.now(tz=timezone.utc)`)
- [ ] Run Playwright E2E: `npx playwright test e2e/authorization.spec.ts`
- [ ] Review conflict scan on staging org — expected 0 blocking/security_risk conflicts

### Phase 1 — Soft Rollout (Days 1–3, per org)

1. Set `authorization_enforcement = False` (soft mode) for the pilot org:
   ```
   PUT /admin/feature-flags/authorization_enforcement  { "enabled": false }
   ```
2. Monitor `events.authorization` logs for `authorization_denied` events.
3. Verify no legitimate user flows are blocked (all denies should be expected).
4. Run `POST /admin/permissions/conflicts/scan` and review results.
5. Resolve any blocking/security_risk conflicts before proceeding.

**Success criteria:** Zero unexpected denials after 24 hours of normal usage.

### Phase 2 — Strict Enforcement (Day 4+)

1. Enable strict mode:
   ```
   PUT /admin/feature-flags/authorization_enforcement  { "enabled": true }
   ```
2. Monitor error rates on document/chat endpoints for 403/404 spikes.
3. Watch `events.authorization` for any `authorization_denied` with `matched_rule=role_permission` on paths that should be allowed.
4. Run conflict scan daily for the first week.

### Phase 3 — Full GA (Day 7+)

- Set `feature_enable_authorization_enforcement = True` in `.env` / deployment config.
- Remove the per-org override (revert to env default):
  ```
  DELETE /admin/feature-flags/authorization_enforcement
  ```
- Authorization enforcement is now always on; the feature flag override is no longer needed.

---

## 9. Monitoring and Observability

### Structured Authorization Events

All authorization decisions in the document access dependency emit structured events via `log_authorization_event()` (structlog logger: `events.authorization`). Log fields:

| Field           | Type     | Description                                         |
|-----------------|----------|-----------------------------------------------------|
| `event`         | string   | `authorization_granted` or `authorization_denied`   |
| `organization_id` | string | Org context of the request                          |
| `user_id`       | string   | Subject user ID                                     |
| `resource_type` | string   | `document`, `collection`, etc.                      |
| `resource_id`   | string   | Resource UUID                                       |
| `action`        | string   | `view`, `chat`, `delete`, etc.                      |
| `decision`      | string   | `allow` or `deny`                                   |
| `deny_reason`   | string?  | DenyReason enum value (null on allow)               |
| `matched_rule`  | string?  | Which rule fired (null for admin bypass)            |
| `request_id`    | string?  | Correlation ID for cross-service tracing            |

### Metrics to Watch

| Metric                                          | Alert Threshold         | Action                                       |
|-------------------------------------------------|-------------------------|----------------------------------------------|
| `authorization_denied` event rate               | > 5% of auth requests   | Investigate deny reasons; check conflicts    |
| `tenant_boundary` deny_reason rate              | Any spike               | Possible attack or misconfigured client      |
| `connector_acl_denied` rate per connector       | > 10% of connector hits | ACL sync may have failed; trigger re-sync    |
| `unknown_resource_type` denies                  | Any occurrence in prod  | New source type missing adapter registration |
| Conflict scan `blocking` severity count         | > 0                     | Immediate review required                    |
| Conflict scan `security_risk` severity count    | > 0                     | Immediate review required; alert on-call     |

### Langfuse Tracing

If Langfuse is enabled (`LANGFUSE_HOST` set), authorization metadata is attached to chat traces:
- `authorization.document_ids_evaluated`
- `authorization.documents_filtered_count`
- `authorization.deny_reasons` (list, deduplicated)

These fields are redacted before export and never contain raw content or credentials.

### Audit Log

All grant/deny CRUD operations are audit-logged:
```
AuditLogService.record(
    action="AUTHZ_ACCESS_GRANTED" | "AUTHZ_ACCESS_DENIED",
    resource_type="document",
    resource_id=...,
    metadata={"matched_rule": ..., "deny_reason": ...}
)
```
Audit records are immutable and retained per org data-retention policy.

---

## 10. Rollback Procedure

If authorization enforcement causes unexpected access denials for legitimate users:

### Immediate Mitigation (< 5 minutes)

1. Disable strict mode for the affected org:
   ```
   PUT /admin/feature-flags/authorization_enforcement  { "enabled": false, "reason": "Rollback: unexpected denials" }
   ```
2. This switches to soft mode immediately — no deployment required.
3. All future requests will log denials but allow access through.

### Root Cause Investigation

1. Query `events.authorization` logs for `decision=deny` events during the incident window.
2. Note the `deny_reason` and `matched_rule` fields.
3. Common causes:
   - `collection_not_accessible`: Document was moved to a restricted collection. Check collection ACLs.
   - `connector_acl_denied`: Connector re-indexed without preserving ACL entries. Trigger re-sync.
   - `explicit_resource_deny`: An admin created a deny that was broader than intended. Remove it.
   - `insufficient_role`: User's role was downgraded. Review the role change.
4. Run `POST /admin/permissions/conflicts/scan` to surface any newly detected conflicts.

### Re-enabling After Fix

1. Verify the fix in staging using `pytest -m authorization_regression`.
2. Run a conflict scan and confirm 0 blocking/security_risk conflicts.
3. Re-enable strict mode:
   ```
   PUT /admin/feature-flags/authorization_enforcement  { "enabled": true }
   ```

---

## 11. Database Row-Level Security

PostgreSQL row-level security (`R04-08`) is a second, database-level tenant boundary under
the policy engine and the repositories' `organization_id` filters. Table coverage and the
policy text are in `docs/06_DATABASE_SCHEMA.md` (`## Row-level security`).

### Modes (`RLS_ENFORCEMENT`)

| Mode | Default for | Effect |
|---|---|---|
| `off` | never by default (an environment other than the four known ones) | No session context is sent. Policies behave like the legacy NULL-permissive policy. |
| `soft` | staging, production (unset) | A bound tenant is filtered by the policy. ORM statements and flushes on a strict table with no tenant bound are allowed, logged (`rls.soft_denial`, once per table per 60 s per process), and counted in `rudix_rls_soft_denials_total{table}`. |
| `strict` | development, test (unset, since 0.5.0) | Every transaction sends `app.rls_mode = 'strict'`, so an unset tenant sees no rows of a strict table and cannot write one. `get_current_principal` also turns on the ORM tenant guard (`enforce_guard`). |

Before 0.5.0 an unset `RLS_ENFORCEMENT` meant `off` in development and test. Set
`RLS_ENFORCEMENT=off` locally to get that back (for example against an old database dump).

How the tenant reaches PostgreSQL:

1. `get_current_principal` authenticates, calls `bind_session_tenant(...)` and then
   `apply_tenant_context(db_session)`, which runs the session-context statement in the
   transaction the authentication lookups already opened.
2. Every later transaction gets it from a SQLAlchemy `after_begin` listener. The tenant
   comes from `session.info["organization_id"]`, else from the request's context variable
   (so `SessionLocal()` sessions opened inside a request are covered too).
3. The statement is `/* rudix:session-context */ SELECT set_config('app.current_organization_id', :org, true), set_config('app.rls_mode', :mode, true)`.
   Statement-count helpers ignore statements with that marker. In soft mode with no tenant
   the statement is skipped (one round trip saved).
4. `maintenance_session()` (`app.db.session`) never binds a tenant and is not counted in
   soft mode. Cross-tenant beat tasks use it: `documents.reap_stale`,
   `connectors.sync.schedule_poll`, `agents.approvals.expire`, `maintenance.retention.purge`,
   `maintenance.partitions.ensure`, and `usage.touch.flush`.

### Lookup tables

Some org-scoped tables are read before any tenant is known: API-key and service-account
hash lookups, share tokens (`/agent/traces/shared/{token}` is unauthenticated),
invitations, SSO discovery and SAML callback, SCIM, connector and Slack OAuth state,
Slack/Teams inbound events, and the public status page. These 15 tables keep the legacy
condition (an unset tenant is never denied) in every mode; a bound tenant still sees only
its own rows.

`users`, `organization_members`, and `auth_refresh_sessions` (`RLS_IDENTITY_TABLES`) get
no policy. They are user-scoped: one user has a home organization, a membership and
refresh sessions in each organization, and a request bound to organization B must still
read the user, list every membership, and revoke the user's sessions in every organization
(logout-all, password change). The ORM guard exempts `User` and `OrganizationMember` for
the same reason.

### Database roles

`deploy/sql/provision_roles.sql` (run by hand, once per database, as the migration owner):

| Role | Attributes | Used by |
|---|---|---|
| migration owner | owns the schema | Alembic via `DATABASE_MIGRATION_URL` |
| `rudix_app` | `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE`, DML grants, not an owner | API and workers via `DATABASE_URL` |
| `rudix_maintenance` | `BYPASSRLS`, same grants | `maintenance_session()` via `DATABASE_MAINTENANCE_URL` |

Policies do not apply to table owners or `BYPASSRLS` roles unless `FORCE ROW LEVEL SECURITY`
is set, so nothing changes until `DATABASE_URL` points at `rudix_app` (or `force_rls.sql`
is applied).

### `FORCE ROW LEVEL SECURITY` (operator SQL)

`deploy/sql/force_rls.sql` sets `FORCE ROW LEVEL SECURITY` on every table with a tenant
policy (`RLS_STRICT_TABLES` and `RLS_LOOKUP_TABLES`); `deploy/sql/unforce_rls.sql` undoes it.
Both are rendered from `app.db.rls` by `backend/scripts/render_force_rls_sql.py`
(`--check` fails on a stale file; `tests/test_force_rls_sql.py` checks the committed files and,
on PostgreSQL, that a non-superuser table owner sees only its tenant under `strict` once the
file is applied). It ships as operator SQL, not as a migration, because it only changes
deployments that still connect as the owner: run it as the migration owner with
`psql -1 -v ON_ERROR_STOP=1 -f deploy/sql/force_rls.sql`. Each statement takes a short
`ACCESS EXCLUSIVE` lock and rewrites no data.

### Rollout

1. `0.4.0`: provision the roles, switch `DATABASE_URL` to `rudix_app`, keep `soft`.
   Watch `rudix_rls_soft_denials_total` and the `RudixRlsSoftDenials` alert for one week;
   every table that shows up is a code path that would break under `strict`.
2. `0.5.0` (now): the chat WebSocket, bot inbound events, the shared agent trace page, and
   pre-authentication audit writes bind a tenant; `strict` is the default in development and
   test, and the F144 isolation cases run under the probe role on PostgreSQL
   (`tests/test_rag_isolation_probe_pg.py`). Staging and production stay `soft`.
3. After the soft-denial week and the role split: apply `deploy/sql/force_rls.sql`, then set
   `RLS_ENFORCEMENT=strict` in staging, then production. Making `strict` the default there
   waits for the Celery binding (`R06-01`).
4. Rollback at any time: `RLS_ENFORCEMENT=soft` or `off` (no deploy of code needed),
   `deploy/sql/unforce_rls.sql`, or point `DATABASE_URL` back at the owner role. The policy
   migration can be downgraded to `20261127_0003`.

### Known gaps before `strict`

- Celery tasks other than the maintenance tasks do not bind a tenant (`R06-01`).
- Closed in 0.5.0: the chat WebSocket and HTTP pipeline (R05-02: every session the pipeline
  opens goes through `bind_pipeline_session`, and the run binds the tenant context variable
  so parallel retrieval branches inherit it; the legacy bodies are gone since S3). Paths that
  run before a principal exists use `bind_resolved_tenant` (session and context variable, no
  ORM guard, counted in `rudix_rls_resolved_tenant_bindings_total{path}`):
  - `agent_trace_share`: the shared agent trace page binds the share token's organisation
    before it reads `agent_runs`, `agent_steps`, and `agent_tool_calls`;
  - `auth_audit`: login, refresh, logout, and SSO bind the organisation they resolved before
    each `audit_logs` insert;
  - `bot_inbound`: Slack/Teams events bind the installation's organisation before the user
    mapping lookup and audit rows; the chat run itself goes through
    `transports/internal.py` (`run_internal_query`, `bind_pipeline_session`).
  `tests/test_rls_resolved_tenant_pg.py` runs each path as the probe role under `strict`.
- Raw SQL (`text()`) is not seen by the soft-mode detector; only ORM statements and flushes
  are counted.

---

## Testing Quick Reference

```bash
# Full regression suite
pytest -m authorization_regression -v

# Tenant-isolation tests only
pytest -m isolation -v

# RLS (R04-08): coverage and soft mode on SQLite, enforcement on PostgreSQL
pytest tests/test_rls_coverage.py tests/test_rls_soft_mode.py
TEST_DATABASE_URL=... pytest tests/test_rls_enforcement_pg.py \
    tests/test_rag_isolation_probe_pg.py tests/test_rls_resolved_tenant_pg.py \
    tests/test_force_rls_sql.py
python scripts/render_force_rls_sql.py --check   # deploy/sql/force_rls.sql is current

# All F336 tests
pytest tests/test_tenant_isolation_f336.py \
       tests/test_role_matrix_f336.py \
       tests/test_rag_authorization_f336.py \
       tests/test_authorization_rollout_f336.py \
       -v

# Frontend unit tests
npx vitest run src/components/admin/AdminConflictsTab.test.tsx

# E2E authorization tests
npx playwright test e2e/authorization.spec.ts --reporter=list
```

---

*Last updated: F336 — Authorization regression suite and rollout plan (June 2026)*
