from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MarketDataIssue:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketDataResult(Generic[T]):
    data: T
    source: str
    fallback_used: bool = False
    issues: tuple[MarketDataIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues
