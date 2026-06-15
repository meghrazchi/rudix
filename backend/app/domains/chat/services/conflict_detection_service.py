"""Conflict detection and multi-source agreement scoring (F301).

Detects when retrieved source documents disagree on factual claims, dates,
values, statuses, or policy statements.  Returns a structured result that
the caller uses to warn users and surface conflicting citations.

Design constraints:
- Raw source chunk text is fed only to the LLM prompt and is NEVER stored or
  returned in the result (no source-text leakage through the conflict path).
- On any LLM or parse failure the service returns a safe fallback
  (agreement_level=full, conflict_detected=False) so the caller can proceed.
- Service is skipped automatically when fewer than 2 distinct documents are
  represented in the retrieved chunks.
- conflict_summary is a brief human-readable sentence describing what was
  found; the LLM prompt strictly forbids quoting raw source text there.
- All chunk context is org-scoped; no cross-org data can reach the detector.
- Trust status from F297 influences preferred-source resolution; verified >
  current > draft > stale overrides LLM advisory preference.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest

logger = logging.getLogger("chat.conflict_detection")

_MAX_CHUNK_CHARS = 1000
_MAX_CHUNKS_PER_DOC = 2
_MAX_DOC_GROUPS = 8
_MAX_SUMMARY_CHARS = 400
_MAX_TOPIC_CHARS = 120
_AGREEMENT_LEVELS: frozenset[str] = frozenset({"full", "partial", "conflicting"})
_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high"})

# Trust status ordering for preferred-source resolution (lower index = preferred).
_TRUST_PREFERENCE_ORDER: list[str] = [
    "verified",
    "current",
    "draft",
    "stale",
    "deprecated",
    "superseded",
    "expired",
    "unknown",
]


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class _ConflictPairOutput(BaseModel):
    doc_label_a: str = Field(default="", max_length=16)
    doc_label_b: str = Field(default="", max_length=16)
    topic: str = Field(default="", max_length=_MAX_TOPIC_CHARS)
    severity: str = Field(default="medium", max_length=16)

    @field_validator("severity", mode="before")
    @classmethod
    def _clean_severity(cls, v: object) -> str:
        s = str(v).strip().lower()
        return s if s in _SEVERITIES else "medium"


class _ConflictDetectorOutput(BaseModel):
    agreement_level: str = Field(default="full", max_length=16)
    conflict_pairs: list[_ConflictPairOutput] = Field(default_factory=list)
    conflict_summary: str = Field(default="", max_length=_MAX_SUMMARY_CHARS)
    preferred_doc_labels: list[str] = Field(default_factory=list)

    @field_validator("agreement_level", mode="before")
    @classmethod
    def _clean_agreement(cls, v: object) -> str:
        s = str(v).strip().lower()
        return s if s in _AGREEMENT_LEVELS else "full"

    @field_validator("conflict_pairs", mode="before")
    @classmethod
    def _clean_pairs(cls, v: object) -> list[dict]:
        if not isinstance(v, list):
            return []
        return v[:20]

    @field_validator("preferred_doc_labels", mode="before")
    @classmethod
    def _clean_labels(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip()[:16] for x in v if str(x).strip()][:_MAX_DOC_GROUPS]

    @field_validator("conflict_summary", mode="before")
    @classmethod
    def _clean_summary(cls, v: object) -> str:
        return str(v).strip()[:_MAX_SUMMARY_CHARS]


# ---------------------------------------------------------------------------
# Public input / result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConflictDetectionChunk:
    """Minimal chunk representation passed into the conflict detector.

    Only text is forwarded to the LLM prompt; chunk_id is kept for
    audit purposes but is never surfaced in the result.
    """

    chunk_id: str
    document_id: str
    text: str
    similarity_score: float = 0.0
    trust_status: str = "current"


@dataclass(frozen=True)
class ConflictPair:
    """One detected disagreement between two source documents.

    document_id_a and document_id_b identify the conflicting documents.
    topic is a brief description of what they disagree on — no raw source text.
    """

    document_id_a: str
    document_id_b: str
    topic: str
    severity: Literal["low", "medium", "high"] = "medium"


@dataclass(frozen=True)
class ConflictDetectionResult:
    """Output of one conflict-detection pass.

    Callers must:
    - Check conflict_detected before showing the conflict_summary to users.
    - Use preferred_document_ids to visually highlight the preferred source.
    - Never store or log raw chunk text obtained via the conflict path.
    - Treat applied=False as "no conflict information available" (not "no conflict").
    """

    conflict_detected: bool
    agreement_level: Literal["full", "partial", "conflicting"]
    conflict_pairs: list[ConflictPair] = field(default_factory=list)
    conflicting_document_ids: list[str] = field(default_factory=list)
    preferred_document_ids: list[str] = field(default_factory=list)
    conflict_summary: str = ""
    applied: bool = False
    model_name: str = ""
    provider_key: str = ""
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a source-conflict analyst for an enterprise document retrieval system.
Your job: determine whether the provided SOURCE GROUPS (each group = one document) \
contain contradictory information on any factual claim.

IMPORTANT RULES:
- A conflict exists when two documents make OPPOSING or INCOMPATIBLE claims about the \
  same fact, value, date, status, obligation, or policy.
- Minor differences in wording or emphasis are NOT conflicts.
- Return ONLY a JSON object — no markdown, no explanation outside the JSON.
- NEVER quote or reproduce raw source text in any field.
- conflict_summary must be a single sentence describing the nature of the disagreement \
  (e.g., "Two documents disagree on the effective date of the pricing policy").

JSON schema:
{
  "agreement_level": "full" | "partial" | "conflicting",
    // "full"       — all documents are consistent with each other.
    // "partial"    — minor disagreements or ambiguities, but no hard contradictions.
    // "conflicting" — at least one pair of documents makes opposing factual claims.

  "conflict_pairs": [
    {
      "doc_label_a": "DOC_1",   // label from the SOURCE GROUPS below
      "doc_label_b": "DOC_2",
      "topic": "brief description of the conflicting claim — no source text",
      "severity": "low" | "medium" | "high"
        // "low"    — minor inconsistency unlikely to mislead.
        // "medium" — clear disagreement on an important fact.
        // "high"   — direct contradiction on a critical claim (date, amount, status).
    }
  ],
  // Empty list when agreement_level is "full".

  "conflict_summary": "One sentence describing what conflicts were found, or empty string.",

  "preferred_doc_labels": ["DOC_1"]
    // Optional: labels of documents that appear more authoritative / up-to-date.
    // Leave empty if all documents are equally trustworthy or agreement_level is "full".
}
"""


def _build_conflict_prompt(
    doc_groups: dict[str, list[str]],
) -> str:
    """Build the LLM prompt from labelled document chunk groups.

    doc_groups maps a short label (e.g. "DOC_1") to a list of chunk texts
    (already truncated). Raw text never leaves this function's return value
    except inside the prompt that goes to the LLM.
    """
    sections: list[str] = []
    for label, texts in doc_groups.items():
        combined = "\n---\n".join(t.strip() for t in texts)
        sections.append(f"[{label}]\n{combined}")
    source_block = "\n\n".join(sections)
    return f"{_SYSTEM_PROMPT}\n\nSOURCE GROUPS:\n{source_block}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ConflictDetectionService:
    """LLM-backed conflict detector for multi-source RAG answers.

    Groups retrieved chunks by document, asks an LLM to detect factual
    contradictions, and returns structured conflict metadata.

    On any error returns a safe fallback (agreement_level=full, no conflicts)
    so the caller never blocks on detector failure.
    """

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self._timeout_seconds = (
            timeout_seconds or settings.conflict_detection_timeout_seconds
        )

    def _resolve_provider(self):  # type: ignore[return]
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory.get_chat_provider()

    @staticmethod
    def _parse_output(raw: str) -> _ConflictDetectorOutput:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in LLM output")
        return _ConflictDetectorOutput.model_validate(json.loads(raw[start : end + 1]))

    @staticmethod
    def _fallback() -> ConflictDetectionResult:
        return ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
            applied=False,
        )

    @staticmethod
    def _resolve_preferred_doc_ids(
        conflicting_doc_ids: list[str],
        trust_by_doc_id: dict[str, str],
        llm_preferred_labels: list[str],
        label_to_doc_id: dict[str, str],
    ) -> list[str]:
        """Determine preferred document IDs when a conflict exists.

        Trust-status order (verified > current > draft > stale > …) takes
        precedence over the LLM's advisory preference.
        """
        if not conflicting_doc_ids:
            return []

        def _trust_rank(doc_id: str) -> int:
            status = trust_by_doc_id.get(doc_id, "unknown")
            try:
                return _TRUST_PREFERENCE_ORDER.index(status)
            except ValueError:
                return len(_TRUST_PREFERENCE_ORDER)

        llm_preferred_ids = [
            label_to_doc_id[label]
            for label in llm_preferred_labels
            if label in label_to_doc_id
        ]

        # Rank all conflicting docs by trust, then by LLM preference as tiebreak.
        ranked = sorted(
            conflicting_doc_ids,
            key=lambda d: (_trust_rank(d), 0 if d in llm_preferred_ids else 1),
        )
        # Return only those that share the best trust rank.
        if ranked:
            best_rank = _trust_rank(ranked[0])
            return [d for d in ranked if _trust_rank(d) == best_rank]
        return []

    async def detect(
        self,
        *,
        chunks: list[ConflictDetectionChunk],
        min_source_docs: int | None = None,
    ) -> ConflictDetectionResult:
        """Detect factual conflicts among retrieved chunks.

        Skips detection (returns safe fallback) when:
        - chunks is empty or represents fewer distinct documents than min_source_docs.
        - Any LLM or parse error occurs.

        Args:
            chunks: Retrieved chunks to analyse. Only text is forwarded to the
                    LLM; chunk_ids never appear in the result.
            min_source_docs: Minimum number of distinct documents required to
                             run detection (defaults to config setting).
        """
        _min_docs = (
            min_source_docs
            if min_source_docs is not None
            else settings.conflict_detection_min_source_docs
        )

        # Group chunks by document, taking up to _MAX_CHUNKS_PER_DOC per doc.
        chunks_by_doc: dict[str, list[ConflictDetectionChunk]] = {}
        trust_by_doc_id: dict[str, str] = {}
        for chunk in chunks:
            if chunk.document_id not in chunks_by_doc:
                chunks_by_doc[chunk.document_id] = []
                trust_by_doc_id[chunk.document_id] = chunk.trust_status
            if len(chunks_by_doc[chunk.document_id]) < _MAX_CHUNKS_PER_DOC:
                chunks_by_doc[chunk.document_id].append(chunk)

        if len(chunks_by_doc) < _min_docs:
            return self._fallback()

        # Build labelled doc groups, limiting to _MAX_DOC_GROUPS documents.
        doc_ids_ordered = list(chunks_by_doc.keys())[:_MAX_DOC_GROUPS]
        label_to_doc_id: dict[str, str] = {}
        doc_groups: dict[str, list[str]] = {}
        for idx, doc_id in enumerate(doc_ids_ordered, 1):
            label = f"DOC_{idx}"
            label_to_doc_id[label] = doc_id
            doc_groups[label] = [
                chunk.text[:_MAX_CHUNK_CHARS]
                for chunk in chunks_by_doc[doc_id]
            ]

        # LLM call.
        started = perf_counter()
        try:
            provider = self._resolve_provider()
            prompt = _build_conflict_prompt(doc_groups)
            request = ChatCompletionRequest(
                prompt=prompt,
                model=settings.openai_llm_model,
                temperature=0.0,
                json_mode=True,
            )
            response = await provider.complete(request)
            raw_text = response.content or ""
            parsed = self._parse_output(raw_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("conflict_detection failed, using safe fallback: %s", exc)
            return self._fallback()

        latency_ms = int((perf_counter() - started) * 1000)

        # Map doc labels back to document IDs for conflict pairs.
        conflict_pairs: list[ConflictPair] = []
        conflicting_doc_id_set: set[str] = set()
        for pair in parsed.conflict_pairs:
            doc_a = label_to_doc_id.get(pair.doc_label_a)
            doc_b = label_to_doc_id.get(pair.doc_label_b)
            if doc_a and doc_b and doc_a != doc_b:
                conflict_pairs.append(
                    ConflictPair(
                        document_id_a=doc_a,
                        document_id_b=doc_b,
                        topic=pair.topic[:_MAX_TOPIC_CHARS],
                        severity=pair.severity,  # type: ignore[arg-type]
                    )
                )
                conflicting_doc_id_set.add(doc_a)
                conflicting_doc_id_set.add(doc_b)

        conflict_detected = parsed.agreement_level == "conflicting" and bool(conflict_pairs)
        agreement_level = parsed.agreement_level  # type: ignore[assignment]

        # If LLM says "conflicting" but returned no valid pairs, degrade to "partial".
        if parsed.agreement_level == "conflicting" and not conflict_pairs:
            agreement_level = "partial"
            conflict_detected = False

        conflicting_document_ids = list(conflicting_doc_id_set)
        preferred_document_ids = self._resolve_preferred_doc_ids(
            conflicting_document_ids,
            trust_by_doc_id,
            parsed.preferred_doc_labels,
            label_to_doc_id,
        )

        logger.debug(
            "conflict_detection agreement=%s conflict_detected=%s pairs=%d latency_ms=%d",
            agreement_level,
            conflict_detected,
            len(conflict_pairs),
            latency_ms,
        )

        return ConflictDetectionResult(
            conflict_detected=conflict_detected,
            agreement_level=agreement_level,
            conflict_pairs=conflict_pairs,
            conflicting_document_ids=conflicting_document_ids,
            preferred_document_ids=preferred_document_ids,
            conflict_summary=parsed.conflict_summary if conflict_detected else "",
            applied=True,
            model_name=settings.openai_llm_model,
            provider_key=settings.llm_default_provider,
            latency_ms=latency_ms,
        )
