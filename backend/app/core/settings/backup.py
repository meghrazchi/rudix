"""Backup, freshness, and restore settings (0.8.0).

Owned by A2. S1 registers the empty class so A2 adds its fields here without editing the
``Settings`` bases; backups stay off by default and the deploy gate keeps its current mode.
"""

from __future__ import annotations

from pydantic import BaseModel


class BackupSettings(BaseModel):
    """Backup bucket, encryption, freshness, and deploy gate settings (filled by A2)."""
