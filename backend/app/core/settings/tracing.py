"""OpenTelemetry tracing settings (0.8.0).

Owned by B3. S1 registers the empty class so B3 adds its fields here without editing the
``Settings`` bases; tracing stays off by default and nothing is exported while no OTLP
endpoint is set.
"""

from __future__ import annotations

from pydantic import BaseModel


class TracingSettings(BaseModel):
    """Tracing switch, exporter endpoint, and sampling (filled by B3)."""
