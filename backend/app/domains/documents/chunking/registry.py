from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domains.documents.chunking.config import ChunkingProfileConfig
    from app.domains.documents.chunking.protocol import ChunkStrategy

# Factory signature: (profile, embedding_model, index_version) -> ChunkStrategy
StrategyFactory = Callable[["ChunkingProfileConfig", str, str], "ChunkStrategy"]


class UnknownStrategyError(ValueError):
    def __init__(self, name: str, known: list[str]) -> None:
        self.strategy_name = name
        known_str = ", ".join(sorted(known)) if known else "(none registered)"
        super().__init__(
            f"Unknown chunking strategy {name!r}. Known strategies: {known_str}"
        )


class StrategyRegistry:
    """Maps strategy names to factory callables that produce configured strategy instances."""

    def __init__(self) -> None:
        self._factories: dict[str, StrategyFactory] = {}

    def register(self, name: str, factory: StrategyFactory) -> None:
        self._factories[name] = factory

    def resolve(
        self,
        profile: ChunkingProfileConfig,
        *,
        embedding_model: str,
        index_version: str,
    ) -> ChunkStrategy:
        factory = self._factories.get(profile.strategy)
        if factory is None:
            raise UnknownStrategyError(profile.strategy, list(self._factories.keys()))
        return factory(profile, embedding_model, index_version)

    def known_strategies(self) -> list[str]:
        return sorted(self._factories.keys())


_registry: StrategyRegistry | None = None


def get_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        from app.domains.documents.chunking.strategies.token_recursive import (
            TokenRecursiveStrategy,
        )

        _registry = StrategyRegistry()
        _registry.register(
            TokenRecursiveStrategy.name,
            TokenRecursiveStrategy.from_profile,
        )
    return _registry
