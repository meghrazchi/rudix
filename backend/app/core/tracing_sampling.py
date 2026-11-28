"""Head sampling for Rudix traces (R08-10).

New traces are sampled by ``TraceIdRatioBased(TRACING_SAMPLE_RATIO)``; local children follow
their parent. A span whose parent came from outside the process (an inbound ``traceparent``)
is handled by ``trust_remote``:

* ``True`` (``TRACING_TRUST_INBOUND_CONTEXT=true``, or the worker reading headers our own
  producer wrote): the remote sampled flag decides, as in the SDK default.
* ``False`` (the API and MCP default): the trace id is kept, so the span stays linked to the
  caller's trace for correlation, but the remote sampled flag and ``tracestate`` are ignored.
  The decision hashes the trace id with a per-process secret salt, so a client can neither
  set the flag nor craft a trace id that forces sampling.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence

from opentelemetry.context import Context
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)
from opentelemetry.trace import Link, SpanKind, TraceState
from opentelemetry.util.types import Attributes

_ID_MASK = (1 << 64) - 1


class UntrustedRemoteParentSampler(Sampler):
    """Ratio sampling of a remote parent's trace id under a secret salt."""

    def __init__(self, rate: float, *, salt: bytes | None = None) -> None:
        self._rate = rate
        self._bound = TraceIdRatioBased.get_bound_for_rate(rate)
        self._salt = salt if salt is not None else secrets.token_bytes(16)

    def _sampled(self, trace_id: int) -> bool:
        digest = hashlib.blake2b(
            trace_id.to_bytes(16, "big"), key=self._salt, digest_size=8
        ).digest()
        return (int.from_bytes(digest, "big") & _ID_MASK) < self._bound

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        decision = Decision.RECORD_AND_SAMPLE if self._sampled(trace_id) else Decision.DROP
        # The caller's ``tracestate`` is not propagated: it is untrusted input.
        return SamplingResult(decision, attributes if decision.is_sampled() else None, TraceState())

    def get_description(self) -> str:
        return f"UntrustedRemoteParentSampler{{{self._rate}}}"


def build_sampler(rate: float, *, trust_remote: bool, salt: bytes | None = None) -> Sampler:
    root = TraceIdRatioBased(rate)
    if trust_remote:
        return ParentBased(root=root)
    untrusted = UntrustedRemoteParentSampler(rate, salt=salt)
    return ParentBased(
        root=root,
        remote_parent_sampled=untrusted,
        remote_parent_not_sampled=untrusted,
        local_parent_sampled=ALWAYS_ON,
        local_parent_not_sampled=ALWAYS_OFF,
    )
