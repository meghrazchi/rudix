from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings


class ChatCompletionsEndpointLike(Protocol):
    async def create(self, **kwargs: object) -> Any:
        ...


class ChatEndpointLike(Protocol):
    completions: ChatCompletionsEndpointLike


class OpenAIClientLike(Protocol):
    chat: ChatEndpointLike


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

    @staticmethod
    def _extract_answer_content(content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
            return "\n".join(text_parts).strip()
        return ""

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

    @staticmethod
    def _is_response_format_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return "response_format" in message and "support" in message

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        if isinstance(exc, OSError):
            return True
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and status_code in {408, 409, 429, 500, 502, 503, 504}:
            return True
        code = str(getattr(exc, "code", "")).lower()
        if code in {"rate_limit_exceeded", "timeout", "server_error"}:
            return True
        name = exc.__class__.__name__.lower()
        return any(
            fragment in name
            for fragment in (
                "timeout",
                "connection",
                "ratelimit",
                "internalserver",
                "tempor",
            )
        )

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
        openai_client: OpenAIClientLike,
    ) -> LLMAnswerResult:
        if not settings.feature_enable_llm:
            raise PermanentLLMServiceError("LLM feature is disabled")
        if not prompt.strip():
            raise PermanentLLMServiceError("prompt is required")

        started = perf_counter()
        retries = 0
        supports_response_format = True
        last_error: Exception | None = None

        attempt = 1
        while attempt <= self.retry_max_attempts:
            request_payload: dict[str, object] = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": "Answer questions only from retrieved document context."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
            }
            if supports_response_format:
                request_payload["response_format"] = {"type": "json_object"}

            try:
                response = await openai_client.chat.completions.create(**request_payload)
            except Exception as exc:
                last_error = exc
                if supports_response_format and self._is_response_format_unsupported(exc):
                    supports_response_format = False
                    continue
                if not self._is_transient_error(exc):
                    raise PermanentLLMServiceError("LLM request failed permanently") from exc
                if attempt >= self.retry_max_attempts:
                    raise TransientLLMServiceError("LLM request failed after retries") from exc
                retries += 1
                backoff = min(self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds)
                await asyncio.sleep(backoff)
                attempt += 1
                continue

            choices = getattr(response, "choices", None) or []
            if not choices:
                last_error = RuntimeError("LLM response contained no choices")
                if attempt >= self.retry_max_attempts:
                    raise PermanentLLMServiceError("LLM response contained no choices")
                retries += 1
                backoff = min(self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds)
                await asyncio.sleep(backoff)
                attempt += 1
                continue

            raw_text = self._extract_answer_content(choices[0].message.content)
            used_fallback_parser = False
            try:
                parsed = self._parse_strict_output(raw_text)
            except (json.JSONDecodeError, ValidationError):
                if attempt < self.retry_max_attempts:
                    retries += 1
                    backoff = min(self.retry_base_seconds * (2 ** (attempt - 1)), self.retry_max_seconds)
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

            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0)) if usage is not None else 0
            completion_tokens = int(getattr(usage, "completion_tokens", 0)) if usage is not None else 0
            total_tokens = (
                int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens))
                if usage is not None
                else prompt_tokens + completion_tokens
            )
            model_name = str(getattr(response, "model", self.model_name))

            return LLMAnswerResult(
                answer=answer,
                not_found=parsed.not_found,
                citations=parsed.citations,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                approximate_cost_usd=self._estimate_cost(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
                latency_ms=int((perf_counter() - started) * 1000),
                retry_count=retries,
                used_fallback_parser=used_fallback_parser,
            )

        if last_error is not None:
            raise TransientLLMServiceError("LLM request failed after retries") from last_error
        raise TransientLLMServiceError("LLM request failed after retries")
