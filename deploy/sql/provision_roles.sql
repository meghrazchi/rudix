-- Rudix database roles for row-level security (R04-01, R04-08).
--
-- Not applied automatically. Run once per database, as the role that owns the schema and
-- runs Alembic migrations (the "migration owner"), then set passwords separately:
--
--   psql "$DATABASE_MIGRATION_URL_PSQL" -v ON_ERROR_STOP=1 -f deploy/sql/provision_roles.sql
--   psql ... -c "ALTER ROLE rudix_app PASSWORD '...'"            -- from your secret store
--   psql ... -c "ALTER ROLE rudix_maintenance PASSWORD '...'"
--
-- Then point the services at the roles:
--   DATABASE_URL             -> rudix_app          (API and workers; RLS applies)
--   DATABASE_MIGRATION_URL   -> migration owner    (Alembic only)
--   DATABASE_MAINTENANCE_URL -> rudix_maintenance  (cross-tenant beat tasks; BYPASSRLS)
--
-- Idempotent: safe to run again after new tables are added (the GRANT ... ON ALL TABLES
-- statements pick them up; default privileges cover tables the owner creates later).
-- No passwords or other secrets belong in this file.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rudix_app') THEN
        CREATE ROLE rudix_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
    ELSE
        ALTER ROLE rudix_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rudix_maintenance') THEN
        CREATE ROLE rudix_maintenance LOGIN NOSUPERUSER BYPASSRLS NOCREATEROLE NOCREATEDB;
    ELSE
        ALTER ROLE rudix_maintenance LOGIN NOSUPERUSER BYPASSRLS NOCREATEROLE NOCREATEDB;
    END IF;
END
$$;

-- Neither role owns any table: row-level security does not apply to a table's owner
-- (FORCE ROW LEVEL SECURITY is not used before 0.5.0).
GRANT USAGE ON SCHEMA public TO rudix_app, rudix_maintenance;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rudix_app, rudix_maintenance;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO rudix_app, rudix_maintenance;

-- Tables and sequences that the migration owner (the role running this script) creates
-- later get the same privileges.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rudix_app, rudix_maintenance;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO rudix_app, rudix_maintenance;
