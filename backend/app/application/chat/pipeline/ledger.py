"""Token ledger of one chat run (R05-01, contract 4.2.5).

S1 records the query embedding and the answer generation only, so ``totals()`` equals the
usage event written today. B1 records every auxiliary call and switches the usage event to
the totals; A1 uses it for cancelled runs.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class LedgerEntry:
    stage: str
    provider_key: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    cost_usd: Decimal | None = None
    estimated: bool = False


@dataclass(frozen=True)
class LedgerTotals:
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost_usd: Decimal | None
    estimated: bool

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TokenLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def record(
        self,
        stage: str,
        provider_key: str | None,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        cost_usd: Decimal | None = None,
        estimated: bool = False,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            stage=stage,
            provider_key=provider_key,
            model=model,
            prompt_tokens=max(0, int(prompt_tokens)),
            completion_tokens=max(0, int(completion_tokens)),
            cached_tokens=max(0, int(cached_tokens)),
            cost_usd=cost_usd,
            estimated=estimated,
        )
        self.entries.append(entry)
        return entry

    def totals(self) -> LedgerTotals:
        """Sum of all entries; the cost is ``None`` when no entry carries one."""
        costs = [entry.cost_usd for entry in self.entries if entry.cost_usd is not None]
        return LedgerTotals(
            prompt_tokens=sum(entry.prompt_tokens for entry in self.entries),
            completion_tokens=sum(entry.completion_tokens for entry in self.entries),
            cached_tokens=sum(entry.cached_tokens for entry in self.entries),
            cost_usd=sum(costs, Decimal("0")) if costs else None,
            estimated=any(entry.estimated for entry in self.entries),
        )

    def by_stage(self) -> dict[str, LedgerTotals]:
        stages: dict[str, TokenLedger] = {}
        for entry in self.entries:
            stages.setdefault(entry.stage, TokenLedger()).entries.append(entry)
        return {stage: ledger.totals() for stage, ledger in stages.items()}
