"""PostgreSQL settings."""

from __future__ import annotations

from pydantic import BaseModel, Field, PostgresDsn

from app.core.settings.enums import RlsEnforcement


class DatabaseSettings(BaseModel):
    database_url: PostgresDsn
    database_echo: bool = False
    # Engine and pool (R04-01). Defaults keep the previous SQLAlchemy behaviour.
    db_pool_size: int = Field(default=5, ge=1, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, ge=0, validation_alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="DB_POOL_TIMEOUT")
    # 0 disables the server-side timeout.
    db_statement_timeout_ms: int = Field(default=0, ge=0)
    db_idle_in_transaction_timeout_ms: int = Field(default=0, ge=0)
    # PgBouncer transaction pooling: no prepared-statement cache, per-transaction timeouts.
    db_pgbouncer_mode: bool = False
    # Owner role for Alembic and a BYPASSRLS role for cross-tenant maintenance tasks.
    database_migration_url: PostgresDsn | None = None
    database_maintenance_url: PostgresDsn | None = None
    # off | soft | strict; unset means soft in staging/production and off elsewhere (R04-08).
    rls_enforcement: RlsEnforcement | None = None
