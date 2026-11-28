# Restore drill log

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Empty: no restore drill has been recorded yet
- `Last Updated`: 2026-11-28
- `Related Docs`: [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md), [README.md](./README.md)

## Purpose

One row per restore drill or real restore. RPO and RTO for `0.8.0` are measured here on
staging; nothing in this repository states them until a row below records a measurement.

## How to add a row

1. Run `deploy/scripts/restore_drill.sh` as described in
   [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md) "Restore drill"; it prints a record.
2. RPO: the time between the moment you restore to (the incident time, or the drill start)
   and the `completed_at` of the marker you restored. RTO: from the start of the drill
   (including provisioning of the scratch stores) to a passing verification and smoke.
3. Name roles, never people. Link follow-up issues instead of describing exploitable details.
4. Remove the scratch stores and decrypted files, then tick the last column.

## Drills

| Date (UTC) | Environment | Run by (role) | Kinds restored | Backup completed_at | RPO (measured) | RTO (measured) | verify_postgres_restore.py | Smoke | Issues and follow-ups | Scratch data removed |
|---|---|---|---|---|---|---|---|---|---|---|
