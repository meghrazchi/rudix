# v1.0.0 — General Availability

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md)

## 1. Purpose

`1.0.0` adds no features. It is the point at which the API contract is frozen, the targets in
the master plan are proven, and compatibility aliases carried through `0.x` are removed.

## 2. Work items

### R10-01 — API contract freeze (M)

- **Change:** Review every `/api/v1` route against `docs/07_API_DESIGN.md`. Fix naming and
  shape inconsistencies now, with aliases, because after this they need a `/api/v2`.
  Snapshot the OpenAPI document as the `1.0` contract and add a CI check that rejects
  breaking changes to it.
- **Done when:** The breaking-change check is a required status check.

### R10-02 — Remove deprecated behaviour (S)

- **Change:** Remove what `0.x` deprecated:
  - `?token=` on the chat WebSocket (`R02-10`).
  - The two legacy 501 routes (`R02-13`).
  - The top-level `detail` error alias (`R04-10`), if the frontend and SDK no longer read it.
  - `CHAT_PIPELINE_V2` and other transition flags.
  - The pre-partition tables kept by `R04-09`, and old Qdrant collections kept by `R06-08`.
- **Done when:** Each removal is listed in the changelog with its replacement.

### R10-03 — Performance sign-off (M)

- **Change:** Run the load suite at target scale on the production topology with the
  graduated flag defaults. Include a soak test of at least 24 hours and a failure-injection
  run. Publish the results next to the `R03-09` baseline.
- **Done when:** Every target in the master plan section 4.6 is met or has an approved,
  documented exception.

### R10-04 — Security review (M)

- **Change:** External penetration test and an internal review of: tenant isolation (RLS in
  strict mode), authentication and MFA, upload handling, prompt-injection defences, MCP and
  agent tool policies, webhook and connector egress (SSRF), and secrets handling. Fix
  critical and high findings before the tag.
- **Done when:** No open critical or high findings, and
  `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` has every item checked or explicitly
  deferred with an owner.

### R10-05 — Operational readiness (S)

- **Change:** On-call rota and escalation in place, runbooks reviewed, a restore drill and a
  failover drill passed within the last quarter, status page (F158) wired to real probes,
  support and incident process documented.

### R10-06 — Documentation pass (M)

- **Change:** Remove or mark every "planned" statement in `docs/` that is now implemented or
  dropped. Regenerate the schema, component, and sequence documents (04, 05, 06) from the
  final design. Write an upgrade guide from `0.9` to `1.0`. Resolve the duplicate document
  numbers (two `16_` and two `23_` files) with redirects from the old names.

## 3. Exit criteria

All six items done, `make check-all` and every required CI gate green on the release
candidate, and one week on staging with no SLO breach.

## 4. Post-1.0 candidates

Not scheduled. Each needs its own spec and approval before work starts.

| Candidate | Why it waits |
|---|---|
| `1.1` Data residency: region-pinned organisations, per-region storage and index | Needs the `0.8.0` topology in more than one region |
| `1.1` Customer-managed encryption keys | Depends on the secret manager from `R08-11` |
| `1.1` WebAuthn and passkeys | Builds on MFA from `R09-02` |
| `1.2` Cross-encoder reranker service | Decide from `0.5.0` latency and cost data; new infrastructure |
| `1.2` Permission-aware semantic answer cache | Cache keys must include the caller's access set; high risk of leaks if rushed |
| `1.2` Dedicated shards or collections for very large tenants | Only when a tenant's size degrades shared-collection latency |
| `1.3` Multi-region active-passive | After data residency |
| `1.x` Additional connectors, mobile or installable web app | Product demand |

## 5. Security Considerations

`R10-04` is the gate. After `1.0.0`, security fixes ship as patch releases and follow
`docs/SECURITY.md`.

## 6. Change Notes

- 2026-11-26: Initial version.
