"""Deployment settings for running several API replicas (0.8.0).

Owned by B1: graceful shutdown drain, readiness dependency scope, and the WebSocket
connection-limit backend. S1 registers the empty class so later tasks add fields here
without editing the ``Settings`` bases; every field added must default to today's behaviour.
"""

from __future__ import annotations

from pydantic import BaseModel


class DeploymentSettings(BaseModel):
    """Shutdown, readiness, and connection-limit settings (filled by B1)."""
