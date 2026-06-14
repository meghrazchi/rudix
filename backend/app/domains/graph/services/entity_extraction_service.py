"""Entity extraction service for Enterprise Graph (F283).

Extracts named entities from document chunks using LLM structured output,
validates the JSON schema strictly, and returns typed entity records ready
for Neo4j upsert via GraphService.

Design:
- Chunks are grouped into configurable batches to respect token/rate limits.
- LLM output is validated against ExtractionBatchSchema (Pydantic strict model).
  Invalid output is rejected and counted; it never reaches the graph.
- Multilingual: original-language names are preserved in original_name; the
  canonical English-normalised form goes in name.
- entity_id is deterministic (UUID5) so the same logical entity extracted from
  multiple documents merges into the same Neo4j node.
- Failures are always recorded in ExtractionBatchResult; callers (document_tasks)
  decide whether to propagate or continue the pipeline.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.logging import get_logger

logger = get_logger("graph.entity_extraction")

# ---------------------------------------------------------------------------
# Supported entity types
# ---------------------------------------------------------------------------

ENTITY_TYPE = Literal[
    "vendor",
    "customer",
    "policy",
    "control",
    "contract",
    "risk",
    "product",
    "project",
    "person",
    "system",
    "process",
    "ticket",
    "date",
    "obligation",
]

ENTITY_TYPE_VALUES: frozenset[str] = frozenset(
    {
        "vendor",
        "customer",
        "policy",
        "control",
        "contract",
        "risk",
        "product",
        "project",
        "person",
        "system",
        "process",
        "ticket",
        "date",
        "obligation",
    }
)

# ---------------------------------------------------------------------------
# Output schema — strict JSON contract for LLM responses
# ---------------------------------------------------------------------------

_MAX_ALIASES = 20
_MAX_NAME_LEN = 512
_MAX_EVIDENCE_LEN = 2000
_MAX_LANG_LEN = 10


class ExtractedEntitySchema(BaseModel):
    """Single entity in LLM structured output. Validated before writing to graph."""

    type: ENTITY_TYPE
    name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    original_name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    aliases: list[str] = Field(default_factory=list, max_length=_MAX_ALIASES)
    language: str = Field(min_length=2, max_length=_MAX_LANG_LEN)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_span: str = Field(min_length=1, max_length=_MAX_EVIDENCE_LEN)
    source_chunk_index: int = Field(ge=0)


class ExtractionBatchSchema(BaseModel):
    """Container returned by the LLM for one batch of chunks."""

    entities: list[ExtractedEntitySchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal result types
# ---------------------------------------------------------------------------


@dataclass
class ExtractedEntityItem:
    """A validated entity ready for Neo4j upsert. entity_id is deterministic."""

    entity_id: uuid.UUID
    type: str
    name: str
    original_name: str
    aliases: list[str]
    language: str
    confidence: float
    evidence_span: str
    source_chunk_index: int


@dataclass
class ExtractionBatchResult:
    entities: list[ExtractedEntityItem] = field(default_factory=list)
    batch_count: int = 0
    total_chunks: int = 0
    validation_errors: int = 0
    llm_errors: int = 0


# ---------------------------------------------------------------------------
# Deterministic entity ID
# ---------------------------------------------------------------------------

# Fixed namespace UUID for UUID5 entity key derivation.
_ENTITY_NAMESPACE = uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")


def _entity_uuid(*, org_id: str, entity_type: str, canonical_name: str) -> uuid.UUID:
    """Derive a deterministic entity UUID from org + type + normalised name.

    The same logical entity extracted from different documents will resolve
    to the same UUID, enabling MERGE-based deduplication in Neo4j.
    """
    key = f"{org_id}:{entity_type}:{canonical_name.lower().strip()}"
    return uuid.uuid5(_ENTITY_NAMESPACE, key)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a named-entity extraction engine for an enterprise knowledge graph.
Extract structured entities from the provided document chunks.

Rules:
- Only extract entities explicitly mentioned in the text.
- Record the EXACT verbatim quote from the text as evidence_span (max 400 chars).
- Preserve the source-language name in original_name; normalise to English in name.
- confidence must be 0.0–1.0; use lower values for ambiguous mentions. Omit entities below 0.3.
- Valid types: vendor, customer, policy, control, contract, risk, product, project,
  person, system, process, ticket, date, obligation.
- source_chunk_index must match the [CHUNK N] header index in the input.
- Return ONLY a JSON object with an "entities" array — no prose, no markdown.

Output format:
{
  "entities": [
    {
      "type": "<type>",
      "name": "<canonical English name>",
      "original_name": "<name exactly as it appears in source text>",
      "aliases": ["<optional alias>"],
      "language": "<ISO 639-1 code, e.g. en, de, fr, es>",
      "confidence": <0.0–1.0>,
      "evidence_span": "<exact verbatim quote from source text>",
      "source_chunk_index": <integer>
    }
  ]
}
"""


def _build_user_prompt(chunk_pairs: list[tuple[int, str]]) -> str:
    """Concatenate (chunk_index, text) pairs into a single extraction prompt."""
    parts = [f"[CHUNK {idx}]\n{text.strip()}" for idx, text in chunk_pairs]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing + schema validation helper
# ---------------------------------------------------------------------------


def _parse_and_validate(raw_json: str) -> tuple[ExtractionBatchSchema | None, str | None]:
    """Parse raw LLM JSON and validate against ExtractionBatchSchema.

    Returns (schema, None) on success or (None, error_message) on any failure.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error: {exc}"
    try:
        schema = ExtractionBatchSchema.model_validate(data)
    except ValidationError as exc:
        return None, f"schema_validation_error: {exc}"
    return schema, None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EntityExtractionService:
    """LLM-backed entity extraction with batching, retries, and schema validation.

    Instantiate once at module level; all state lives in the provider client.
    """

    def __init__(
        self,
        *,
        batch_size: int = 10,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self._batch_size = max(1, batch_size)
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def extract_from_chunks(
        self,
        *,
        chunks: list[tuple[int, str]],
        document_language: str | None = None,
        organization_id: str = "",
    ) -> ExtractionBatchResult:
        """Extract entities from all provided chunks, batching LLM calls.

        Args:
            chunks: list of (chunk_index, text) pairs.
            document_language: ISO code of the document language (informational).
            organization_id: used to derive deterministic entity UUIDs.

        Returns an ExtractionBatchResult with all schema-validated entities.
        Errors in individual batches are counted but do not raise.
        """
        from app.domains.ai.providers.factory import default_provider_factory
        from app.domains.ai.providers.protocols import ChatCompletionRequest

        provider = default_provider_factory.get_chat_provider()
        result = ExtractionBatchResult(total_chunks=len(chunks))

        batches = [
            chunks[i : i + self._batch_size]
            for i in range(0, len(chunks), self._batch_size)
        ]
        result.batch_count = len(batches)

        for batch in batches:
            valid_pairs = [(idx, text) for idx, text in batch if text.strip()]
            if not valid_pairs:
                continue

            prompt = _build_user_prompt(valid_pairs)
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
                except asyncio.TimeoutError:
                    logger.warning(
                        "entity_extraction.timeout",
                        attempt=attempt,
                        timeout_seconds=self._timeout_seconds,
                    )
                    if attempt == self._max_retries:
                        result.llm_errors += 1
                except Exception as exc:
                    logger.warning(
                        "entity_extraction.llm_error",
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
                logger.warning("entity_extraction.validation_error", error=err)
                result.validation_errors += 1
                continue

            for entity in batch_schema.entities:
                # Clamp source_chunk_index to one of the indices in this batch.
                if entity.source_chunk_index not in valid_indices:
                    entity_chunk_index = valid_pairs[0][0]
                else:
                    entity_chunk_index = entity.source_chunk_index

                result.entities.append(
                    ExtractedEntityItem(
                        entity_id=_entity_uuid(
                            org_id=organization_id,
                            entity_type=entity.type,
                            canonical_name=entity.name,
                        ),
                        type=entity.type,
                        name=entity.name,
                        original_name=entity.original_name,
                        aliases=list(entity.aliases),
                        language=entity.language,
                        confidence=entity.confidence,
                        evidence_span=entity.evidence_span,
                        source_chunk_index=entity_chunk_index,
                    )
                )

        return result
