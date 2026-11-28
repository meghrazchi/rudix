"""Deployment settings for running several API replicas (0.8.0).

Owned by B1: graceful shutdown drain, readiness dependency scope, and the WebSocket
connection-limit backend. S1 registers the empty class so later tasks add fields here
without editing the ``Settings`` bases; every field added must default to today's behaviour.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import NoDecode

# Dependency names ``GET /api/v1/ready`` reports (``app/api/health.py``). ``neo4j`` is present
# only with the enterprise graph and ``redis_cache`` only when ``REDIS_CACHE_URL`` is set.
READINESS_DEPENDENCY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "postgres",
        "redis",
        "redis_cache",
        "rabbitmq",
        "qdrant",
        "minio",
        "neo4j",
        "openai_config",
    }
)

WsConnectionLimitBackend = Literal["memory", "redis"]


class DeploymentSettings(BaseModel):
    """Shutdown, readiness, and connection-limit settings (filled by B1)."""

    # R08-03: where the per-user chat WebSocket connection limit is counted. ``memory`` (the
    # default) counts per process, as before 0.8.0; ``redis`` holds one lease per connection
    # in a sorted set shared by every replica, refreshed by the WebSocket heartbeat.
    ws_chat_connection_limit_backend: WsConnectionLimitBackend = "memory"
    # Lifetime of one connection lease; a crashed replica's leases expire after it. Must
    # exceed two heartbeat intervals so one late heartbeat never drops a live lease.
    ws_chat_connection_lease_seconds: int = Field(default=90, ge=10, le=3600)
    # R08-02: seconds the lifespan shutdown waits for dropped chat runs (resume grace
    # watchers) before closing Redis and the database. 0 keeps the pre-0.8.0 behaviour.
    api_shutdown_drain_seconds: float = Field(default=0.0, ge=0.0, le=120.0)
    # R08-02: dependencies whose failure makes ``/ready`` answer 503 (comma list). Unset
    # means every dependency, as before 0.8.0; the body always reports all of them.
    readiness_required_dependencies: Annotated[list[str] | None, NoDecode] = None

    @field_validator("readiness_required_dependencies", mode="before")
    @classmethod
    def _parse_readiness_dependencies(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        raw_items = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw_items, list | tuple | set | frozenset):
            raise ValueError("readiness_required_dependencies must be a comma list or list")
        names: list[str] = []
        for item in raw_items:
            name = str(item).strip().lower()
            if not name or name in names:
                continue
            if name not in READINESS_DEPENDENCY_NAMES:
                allowed = ", ".join(sorted(READINESS_DEPENDENCY_NAMES))
                raise ValueError(
                    f"readiness_required_dependencies: unknown dependency {name!r} "
                    f"(allowed: {allowed})"
                )
            names.append(name)
        return names or None

    @model_validator(mode="after")
    def _lease_outlives_two_heartbeats(self) -> DeploymentSettings:
        # Only the ``redis`` backend uses the lease: with ``memory`` (the default) a heartbeat
        # interval that was valid before 0.8.0 (up to 120 s) must keep starting the app.
        if self.ws_chat_connection_limit_backend != "redis":
            return self
        heartbeat = getattr(self, "ws_chat_heartbeat_interval_seconds", None)
        if heartbeat is None:
            return self
        if self.ws_chat_connection_lease_seconds <= 2 * int(heartbeat):
            raise ValueError(
                "WS_CHAT_CONNECTION_LEASE_SECONDS must be greater than twice "
                "WS_CHAT_HEARTBEAT_INTERVAL_SECONDS"
            )
        return self
