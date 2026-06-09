from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.domains.ai.providers.errors import (
    ProviderInternalError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionProvider

if TYPE_CHECKING:
    pass


class LLMServiceError(RuntimeError):
    """Base class for LLM service errors."""


class TransientLLMServiceError(LLMServiceError):
    """Retryable provider errors."""


class PermanentLLMServiceError(LLMServiceError):
    """Non-retryable provider errors."""


class ParsedCitation(BaseModel):
    document_id: str
    chunk_id: str
    filename: str | None = None
    page_number: int | None = None
    text_snippet: str | None = None


class ParsedLLMOutput(BaseModel):
    answer: str
    not_found: bool
    citations: list[ParsedCitation] = Field(default_factory=list)


@dataclass(frozen=True)
class LLMAnswerResult:
    answer: str
    not_found: bool
    citations: list[ParsedCitation]
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    approximate_cost_usd: Decimal
    latency_ms: int
    retry_count: int
    used_fallback_parser: bool


_TRANSIENT_PROVIDER_ERRORS = (
    ProviderTimeoutError,
    ProviderQuotaExceededError,
    ProviderUnavailableError,
    ProviderInternalError,
)


class LLMService:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        retry_max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        input_cost_per_million_tokens_usd: float | None = None,
        output_cost_per_million_tokens_usd: float | None = None,
        max_answer_chars: int = 8000,
        provider: ChatCompletionProvider | None = None,
    ) -> None:
        self.model_name = (model_name or settings.openai_llm_model).strip()
        self.retry_max_attempts = retry_max_attempts or settings.llm_retry_max_attempts
        self.retry_base_seconds = retry_base_seconds or settings.llm_retry_base_seconds
        self.retry_max_seconds = retry_max_seconds or settings.llm_retry_max_seconds
        self.input_cost_per_million_tokens_usd = (
            input_cost_per_million_tokens_usd
            if input_cost_per_million_tokens_usd is not None
            else settings.openai_llm_input_cost_per_million_tokens_usd
        )
        self.output_cost_per_million_tokens_usd = (
            output_cost_per_million_tokens_usd
            if output_cost_per_million_tokens_usd is not None
            else settings.openai_llm_output_cost_per_million_tokens_usd
        )
        self.max_answer_chars = max_answer_chars
        self._provider = provider

    def _resolve_provider(self) -> ChatCompletionProvider:
        if self._provider is None:
            from app.domains.ai.providers.factory import default_provider_factory

            self._provider = default_provider_factory.get_chat_provider()
        return self._provider

    @staticmethod
    def _parse_strict_output(raw_text: str) -> ParsedLLMOutput:
        payload = json.loads(raw_text)
        return ParsedLLMOutput.model_validate(payload)

    @staticmethod
    def _parse_fallback_output(raw_text: str) -> ParsedLLMOutput:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object found in model output")
        payload = json.loads(raw_text[start : end + 1])
        return ParsedLLMOutput.model_validate(payload)

    def _estimate_cost(self, *, prompt_tokens: int, completion_tokens: int) -> Decimal:
        input_cost = (Decimal(prompt_tokens) / Decimal(1_000_000)) * Decimal(
            str(self.input_cost_per_million_tokens_usd)
        )
        output_cost = (Decimal(completion_tokens) / Decimal(1_000_000)) * Decimal(
            str(self.output_cost_per_million_tokens_usd)
        )
        return input_cost + output_cost

    async def generate_answer(
        self,
        *,
        prompt: str,
    ) -> LLMAnswerResult:
        if not settings.feature_enable_llm:
            raise PermanentLLMServiceError("LLM feature is disabled")
        if not prompt.strip():
            raise PermanentLLMServiceError("prompt is required")

        provider = self._resolve_provider()
        started = perf_counter()
        retries = 0
        supports_json_mode = True
        last_error: Exception | None = None

        attempt = 1
        while attempt <= self.retry_max_attempts:
            request = ChatCompletionRequest(
                prompt=prompt,
                model=self.model_name,
                temperature=0.0,
                json_mode=supports_json_mode,
            )
            try:
                response = await provider.complete(request)
            except UnsupportedCapabilityError:
                if supports_json_mode:
                    supports_json_mode = False
                    continue
                raise PermanentLLMServiceError(
                    "LLM does not support JSON mode and fallback failed"
                )
            except _TRANSIENT_PROVIDER_ERRORS as exc:
                last_error = exc
                if attempt >= self.retry_max_attempts:
                    raise TransientLLMServiceError(
                        "LLM request failed after retries"
                    ) from exc
                retries += 1
                backoff = min(
                    self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds
                )
                await asyncio.sleep(backoff)
                attempt += 1
                continue
            except Exception as exc:
                raise PermanentLLMServiceError("LLM request failed permanently") from exc

            raw_text = response.content
            if not raw_text:
                last_error = RuntimeError("LLM response contained no content")
                if attempt >= self.retry_max_attempts:
                    raise PermanentLLMServiceError("LLM response contained no content")
                retries += 1
                backoff = min(
                    self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds
                )
                await asyncio.sleep(backoff)
                attempt += 1
                continue

            used_fallback_parser = False
            try:
                parsed = self._parse_strict_output(raw_text)
            except (json.JSONDecodeError, ValidationError):
                if attempt < self.retry_max_attempts:
                    retries += 1
                    backoff = min(
                        self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue
                try:
                    parsed = self._parse_fallback_output(raw_text)
                    used_fallback_parser = True
                except (ValueError, json.JSONDecodeError, ValidationError):
                    parsed = ParsedLLMOutput(answer="", not_found=True, citations=[])
                    used_fallback_parser = True

            answer = parsed.answer.replace("\x00", "").strip()
            if len(answer) > self.max_answer_chars:
                answer = answer[: self.max_answer_chars].strip()
            if not answer:
                parsed = ParsedLLMOutput(answer="", not_found=True, citations=[])

            return LLMAnswerResult(
                answer=answer,
                not_found=parsed.not_found,
                citations=parsed.citations,
                model_name=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                approximate_cost_usd=self._estimate_cost(
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                ),
                latency_ms=int((perf_counter() - started) * 1000),
                retry_count=retries,
                used_fallback_parser=used_fallback_parser,
            )

        if last_error is not None:
            raise TransientLLMServiceError("LLM request failed after retries") from last_error
        raise TransientLLMServiceError("LLM request failed after retries")
