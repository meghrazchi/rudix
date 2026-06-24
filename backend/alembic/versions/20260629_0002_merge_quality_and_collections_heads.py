"""Merge the document quality and collections slug migration heads.

Revision ID: 20260629_0002
Revises: 20260624_0009, 20260629_0001
Create Date: 2026-06-29 00:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "20260629_0002"
down_revision: str | tuple[str, ...] | None = ("20260624_0009", "20260629_0001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge heads without changing schema."""


def downgrade() -> None:
    """Split heads back out on downgrade."""
