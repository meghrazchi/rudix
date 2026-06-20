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
from app.domains.ai.providers.protocols import ChatCompletionProvider, ChatCompletionRequest

if TYPE_CHECKING:
    from app.domains.ai.profile.schemas import ResolvedTaskProfile
    from app.domains.ai.providers.protocols import ChatCompletionResponse


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
    provider_key: str = "openai"
    fallback_used: bool = False
    fallback_from: str | None = None
    fallback_to: str | None = None
    fallback_reason: str | None = None


_TRANSIENT_PROVIDER_ERRORS = (
    ProviderTimeoutError,
    ProviderQuotaExceededError,
    ProviderUnavailableError,
    ProviderInternalError,
)

# Rough chars-per-token estimate used for context-window budget checks.
_CHARS_PER_TOKEN = 4
# Reserve 15 % of the context window for the model's completion.
_CONTEXT_WINDOW_PROMPT_BUDGET = 0.85


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

    def _resolve_provider(self, provider_key: str | None = None) -> ChatCompletionProvider:
        if self._provider is not None:
            return self._provider
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory.get_chat_provider(provider_key)

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

    @staticmethod
    def _apply_context_window(prompt: str, context_window: int | None) -> str:
        """Truncate prompt to fit within the model's context-window budget."""
        if context_window is None:
            return prompt
        max_chars = int(context_window * _CONTEXT_WINDOW_PROMPT_BUDGET * _CHARS_PER_TOKEN)
        if len(prompt) <= max_chars:
            return prompt
        return prompt[:max_chars]

    async def _run_with_retry(
        self,
        *,
        prompt: str,
        provider: ChatCompletionProvider,
        model_name: str,
        max_attempts: int,
    ) -> tuple[ChatCompletionResponse, ParsedLLMOutput, bool, int]:
        """Run a completion with retry loop.

        Returns (raw_response, parsed_output, used_fallback_parser, retry_count).
        Raises TransientLLMServiceError when all retries are exhausted.
        Raises PermanentLLMServiceError for non-retryable failures.
        """
        supports_json_mode = True
        retries = 0
        last_error: Exception | None = None

        attempt = 1
        while attempt <= max_attempts:
            request = ChatCompletionRequest(
                prompt=prompt,
                model=model_name,
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
                ) from None
            except _TRANSIENT_PROVIDER_ERRORS as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise TransientLLMServiceError("LLM request failed after retries") from exc
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
                if attempt >= max_attempts:
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
                if attempt < max_attempts:
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

            return response, parsed, used_fallback_parser, retries

        if last_error is not None:
            raise TransientLLMServiceError("LLM request failed after retries") from last_error
        raise TransientLLMServiceError("LLM request failed after retries")

    def _normalise_answer(self, parsed: ParsedLLMOutput) -> tuple[str, bool, list[ParsedCitation]]:
        answer = parsed.answer.replace("\x00", "").strip()
        if len(answer) > self.max_answer_chars:
            answer = answer[: self.max_answer_chars].strip()
        if not answer:
            return "", True, []
        return answer, parsed.not_found, parsed.citations

    def _build_result(
        self,
        *,
        response: ChatCompletionResponse,
        parsed: ParsedLLMOutput,
        used_fallback_parser: bool,
        retry_count: int,
        started: float,
        provider_key: str,
        fallback_used: bool = False,
        fallback_from: str | None = None,
        fallback_to: str | None = None,
        fallback_reason: str | None = None,
    ) -> LLMAnswerResult:
        answer, not_found, citations = self._normalise_answer(parsed)
        return LLMAnswerResult(
            answer=answer,
            not_found=not_found,
            citations=citations,
            model_name=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            approximate_cost_usd=self._estimate_cost(
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            ),
            latency_ms=int((perf_counter() - started) * 1000),
            retry_count=retry_count,
            used_fallback_parser=used_fallback_parser,
            provider_key=provider_key,
            fallback_used=fallback_used,
            fallback_from=fallback_from,
            fallback_to=fallback_to,
            fallback_reason=fallback_reason,
        )

    async def generate_answer(
        self,
        *,
        prompt: str,
        resolved_profile: ResolvedTaskProfile | None = None,
    ) -> LLMAnswerResult:
        if not settings.feature_enable_llm:
            raise PermanentLLMServiceError("LLM feature is disabled")
        if not prompt.strip():
            raise PermanentLLMServiceError("prompt is required")

        # Determine routing from profile; fall back to instance-level defaults.
        if resolved_profile is not None:
            primary_provider_key = resolved_profile.provider_type
            primary_model = resolved_profile.base_model
            fallback_key: str | None = (
                resolved_profile.fallback_provider_key
                if settings.feature_enable_provider_fallback
                else None
            )
            effective_prompt = self._apply_context_window(prompt, resolved_profile.context_window)
            primary_provider = self._resolve_provider(primary_provider_key)
        else:
            # No profile: honour the injected provider (self._provider) when present,
            # then fall back to factory default.
            primary_provider_key = settings.llm_default_provider
            primary_model = self.model_name
            fallback_key = None
            effective_prompt = prompt
            primary_provider = self._resolve_provider(None)

        started = perf_counter()

        try:
            response, parsed, used_fallback_parser, retry_count = await self._run_with_retry(
                prompt=effective_prompt,
                provider=primary_provider,
                model_name=primary_model,
                max_attempts=self.retry_max_attempts,
            )
        except TransientLLMServiceError as primary_exc:
            if not fallback_key:
                raise

            fallback_reason = (
                type(primary_exc.__cause__).__name__
                if primary_exc.__cause__
                else type(primary_exc).__name__
            )
            fallback_provider = self._resolve_provider(fallback_key)

            # Use the fallback provider's configured model name when available.
            fb_model = getattr(fallback_provider, "_model_name", None) or primary_model

            try:
                # Retry with original (untruncated) prompt: fallback likely has larger context.
                response, parsed, used_fallback_parser, retry_count = await self._run_with_retry(
                    prompt=prompt,
                    provider=fallback_provider,
                    model_name=fb_model,
                    max_attempts=self.retry_max_attempts,
                )
            except (TransientLLMServiceError, PermanentLLMServiceError):
                raise TransientLLMServiceError(
                    "LLM request failed on primary and fallback provider"
                ) from primary_exc

            return self._build_result(
                response=response,
                parsed=parsed,
                used_fallback_parser=used_fallback_parser,
                retry_count=retry_count,
                started=started,
                provider_key=fallback_key,
                fallback_used=True,
                fallback_from=primary_provider_key,
                fallback_to=fallback_key,
                fallback_reason=fallback_reason,
            )

        return self._build_result(
            response=response,
            parsed=parsed,
            used_fallback_parser=used_fallback_parser,
            retry_count=retry_count,
            started=started,
            provider_key=primary_provider_key,
        )
