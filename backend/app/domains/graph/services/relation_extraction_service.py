"""Relation extraction service for Enterprise Graph (F284).

Extracts typed relationships between already-identified entities from document
chunks using LLM structured output, validates the JSON schema strictly, and
returns relation records ready for Neo4j upsert via GraphService.

Design:
- Receives (chunk_index, text) pairs and a name→entity_id lookup built by
  the caller after entity extraction (F283).
- LLM output is validated against RelationExtractionBatchSchema.
  Invalid output is rejected and counted; it never reaches the graph.
- relation_id is deterministic (UUID5) so the same logical relation extracted
  from multiple documents merges to the same Neo4j edge.
- Failures are counted in RelationExtractionBatchResult; callers decide
  whether to propagate or continue the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.logging import get_logger
from app.domains.ai.providers.factory import default_provider_factory

logger = get_logger("graph.relation_extraction")

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

RELATION_TYPE = Literal[
    "MENTIONS",
    "OWNS",
    "RELATES_TO",
    "COVERS_CONTROL",
    "CONTAINS_OBLIGATION",
    "PROVIDES_SERVICE_TO",
    "SUPERSEDES",
    "AFFECTS",
    "DEPENDS_ON",
]

RELATION_TYPE_VALUES: frozenset[str] = frozenset(
    {
        "MENTIONS",
        "OWNS",
        "RELATES_TO",
        "COVERS_CONTROL",
        "CONTAINS_OBLIGATION",
        "PROVIDES_SERVICE_TO",
        "SUPERSEDES",
        "AFFECTS",
        "DEPENDS_ON",
    }
)

RelationStatus = Literal["unverified", "verified", "rejected", "low_confidence"]

# ---------------------------------------------------------------------------
# Output schema — strict JSON contract for LLM responses
# ---------------------------------------------------------------------------

_MAX_EVIDENCE_LEN = 2000
_MAX_NAME_LEN = 512


class ExtractedRelationSchema(BaseModel):
    """Single relation in LLM structured output. Validated before writing to graph."""

    from_entity_name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    to_entity_name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    rel_type: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_span: str = Field(min_length=1, max_length=_MAX_EVIDENCE_LEN)
    source_chunk_index: int = Field(ge=0)

    @field_validator("rel_type")
    @classmethod
    def validate_rel_type(cls, v: str) -> str:
        upper = v.upper().strip()
        if upper not in RELATION_TYPE_VALUES:
            raise ValueError(
                f"Unknown relation type '{v}'. "
                f"Valid types: {', '.join(sorted(RELATION_TYPE_VALUES))}"
            )
        return upper


class RelationExtractionBatchSchema(BaseModel):
    """Container returned by the LLM for one batch of chunks."""

    relations: list[ExtractedRelationSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal result types
# ---------------------------------------------------------------------------


@dataclass
class ExtractedRelationItem:
    """A validated relation ready for Neo4j upsert."""

    relation_id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    from_entity_name: str
    to_entity_name: str
    rel_type: str
    confidence: float
    evidence_span: str
    source_chunk_index: int


@dataclass
class RelationExtractionBatchResult:
    relations: list[ExtractedRelationItem] = field(default_factory=list)
    batch_count: int = 0
    total_chunks: int = 0
    skipped_unknown_entity: int = 0
    validation_errors: int = 0
    llm_errors: int = 0


# ---------------------------------------------------------------------------
# Deterministic relation ID
# ---------------------------------------------------------------------------

_RELATION_NAMESPACE = uuid.UUID("b8f3e1d2-9a4c-5f7e-8b6d-0c1a2e3f4d5e")


def _relation_uuid(
    *, org_id: str, from_entity_id: str, rel_type: str, to_entity_id: str
) -> uuid.UUID:
    """Derive a deterministic relation UUID from org + entity pair + type.

    Same logical relationship extracted from multiple documents merges into
    the same Neo4j edge via MERGE, preventing logical duplicates.
    """
    key = f"{org_id}:{from_entity_id}:{rel_type}:{to_entity_id}"
    return uuid.uuid5(_RELATION_NAMESPACE, key)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a relationship extraction engine for an enterprise knowledge graph.
Given document chunk text and a list of known entities, identify typed relationships between those entities.

Rules:
- Only extract relationships that are EXPLICITLY supported by the text.
- from_entity_name and to_entity_name MUST match names from the provided entity list (canonical English names).
- Record the EXACT verbatim quote from the text as evidence_span (max 400 chars).
- confidence must be 0.0-1.0; omit relationships below 0.3.
- Valid rel_type values: MENTIONS, OWNS, RELATES_TO, COVERS_CONTROL, CONTAINS_OBLIGATION,
  PROVIDES_SERVICE_TO, SUPERSEDES, AFFECTS, DEPENDS_ON.
- source_chunk_index must match the [CHUNK N] header in the input.
- Do NOT invent entity names not present in the entity list.
- Return ONLY a JSON object with a "relations" array — no prose, no markdown.

Output format:
{
  "relations": [
    {
      "from_entity_name": "<canonical English entity name>",
      "to_entity_name": "<canonical English entity name>",
      "rel_type": "<REL_TYPE>",
      "confidence": <0.0-1.0>,
      "evidence_span": "<exact verbatim quote>",
      "source_chunk_index": <integer>
    }
  ]
}
"""


def _build_user_prompt(
    chunk_pairs: list[tuple[int, str]],
    entity_names_by_chunk: dict[int, list[str]],
) -> str:
    """Concatenate chunks with entity context into a single extraction prompt."""
    parts: list[str] = []
    for idx, text in chunk_pairs:
        names = entity_names_by_chunk.get(idx, [])
        entity_section = (
            f"Known entities in this chunk: {', '.join(names)}"
            if names
            else "Known entities: (none)"
        )
        parts.append(f"[CHUNK {idx}]\n{entity_section}\n\n{text.strip()}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing + schema validation helper
# ---------------------------------------------------------------------------


def _parse_and_validate(
    raw_json: str,
) -> tuple[RelationExtractionBatchSchema | None, str | None]:
    """Parse raw LLM JSON and validate against RelationExtractionBatchSchema.

    Returns (schema, None) on success or (None, error_message) on failure.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error: {exc}"
    try:
        schema = RelationExtractionBatchSchema.model_validate(data)
    except ValidationError as exc:
        return None, f"schema_validation_error: {exc}"
    return schema, None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RelationExtractionService:
    """LLM-backed relation extraction with batching, retries, and schema validation.

    Requires entity extraction results (F283) to build the name→entity_id lookup
    so extracted relation references can be resolved to stable entity UUIDs.
    """

    def __init__(
        self,
        *,
        batch_size: int = 10,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._batch_size = max(1, batch_size)
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._confidence_threshold = confidence_threshold

    async def extract_from_chunks(
        self,
        *,
        chunks: list[tuple[int, str]],
        entity_name_to_id: dict[str, uuid.UUID],
        entity_names_by_chunk: dict[int, list[str]],
        organization_id: str = "",
    ) -> RelationExtractionBatchResult:
        """Extract relationships between known entities from chunks.

        Args:
            chunks: list of (chunk_index, text) pairs.
            entity_name_to_id: mapping from canonical entity name (lowercased) to UUID.
            entity_names_by_chunk: chunk_index → list of canonical entity names present.
            organization_id: used to derive deterministic relation UUIDs.

        Returns a RelationExtractionBatchResult. Errors in individual batches
        are counted but do not raise.
        """
        from app.domains.ai.providers.protocols import ChatCompletionRequest

        provider = default_provider_factory.get_chat_provider()
        result = RelationExtractionBatchResult(total_chunks=len(chunks))

        batches = [
            chunks[i : i + self._batch_size] for i in range(0, len(chunks), self._batch_size)
        ]
        result.batch_count = len(batches)

        for batch in batches:
            valid_pairs = [(idx, text) for idx, text in batch if text.strip()]
            if not valid_pairs:
                continue

            prompt = _build_user_prompt(valid_pairs, entity_names_by_chunk)
            valid_indices = {idx for idx, _ in valid_pairs}
            raw_response: str | None = None

            for attempt in range(self._max_retries + 1):
                try:
                    response = await asyncio.wait_for(
                        provider.complete(
                            ChatCompletionRequest(
                                system_message=_SYSTEM_PROMPT,
                                prompt=prompt,
                                temperature=0.0,
                                json_mode=True,
                            )
                        ),
                        timeout=self._timeout_seconds,
                    )
                    raw_response = response.content
                    break
                except TimeoutError:
                    logger.warning(
                        "relation_extraction.timeout",
                        attempt=attempt,
                        timeout_seconds=self._timeout_seconds,
                    )
                    if attempt == self._max_retries:
                        result.llm_errors += 1
                except Exception as exc:
                    logger.warning(
                        "relation_extraction.llm_error",
                        attempt=attempt,
                        error_type=exc.__class__.__name__,
                        detail=str(exc),
                    )
                    if attempt == self._max_retries:
                        result.llm_errors += 1

            if raw_response is None:
                continue

            batch_schema, err = _parse_and_validate(raw_response)
            if err is not None:
                logger.warning("relation_extraction.validation_error", error=err)
                result.validation_errors += 1
                continue

            for rel in batch_schema.relations:
                if rel.source_chunk_index not in valid_indices:
                    chunk_index = valid_pairs[0][0]
                else:
                    chunk_index = rel.source_chunk_index

                # Resolve entity names to UUIDs from the lookup table.
                from_id = entity_name_to_id.get(rel.from_entity_name.lower().strip())
                to_id = entity_name_to_id.get(rel.to_entity_name.lower().strip())
                if from_id is None or to_id is None:
                    logger.debug(
                        "relation_extraction.unknown_entity",
                        from_entity=rel.from_entity_name,
                        to_entity=rel.to_entity_name,
                        rel_type=rel.rel_type,
                    )
                    result.skipped_unknown_entity += 1
                    continue

                result.relations.append(
                    ExtractedRelationItem(
                        relation_id=_relation_uuid(
                            org_id=organization_id,
                            from_entity_id=str(from_id),
                            rel_type=rel.rel_type,
                            to_entity_id=str(to_id),
                        ),
                        from_entity_id=from_id,
                        to_entity_id=to_id,
                        from_entity_name=rel.from_entity_name,
                        to_entity_name=rel.to_entity_name,
                        rel_type=rel.rel_type,
                        confidence=rel.confidence,
                        evidence_span=rel.evidence_span,
                        source_chunk_index=chunk_index,
                    )
                )

        return result

    def compute_initial_status(self, confidence: float) -> RelationStatus:
        """Return low_confidence if below threshold, else unverified."""
        if confidence < self._confidence_threshold:
            return "low_confidence"
        return "unverified"
