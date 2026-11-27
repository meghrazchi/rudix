"""PostgreSQL settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    PostgresDsn,
)

if TYPE_CHECKING:
    pass


class DatabaseSettings(BaseModel):
    database_url: PostgresDsn
    database_echo: bool = False
