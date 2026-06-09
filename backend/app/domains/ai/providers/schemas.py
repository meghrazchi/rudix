from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CostBehavior(str, Enum):
    per_token = "per_token"
    fixed = "fixed"
    free = "free"


@dataclass(frozen=True)
class ModelCapability:
    provider: str
    model_name: str
    context_window: int
    max_input_tokens: int
    is_chat_model: bool = True
    is_embedding_model: bool = False
    embedding_dimension: int | None = None
    supports_json_mode: bool = True
    supports_streaming: bool = True
    supports_tool_calling: bool = False
    cost_behavior: CostBehavior = CostBehavior.per_token
