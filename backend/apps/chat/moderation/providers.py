"""
Moderation AI provider interfaces and implementations.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class ProviderResult:
    verdict: str  # "allowed", "blocked", "flagged"
    latency_ms: float = 0.0
    flagged: bool = False
    reason: str = ""
    raw_response: dict = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.verdict == "allowed"

    @property
    def is_blocked(self) -> bool:
        return self.verdict == "blocked"

    @property
    def is_flagged(self) -> bool:
        return self.verdict == "flagged"


class BaseModerationProvider(ABC):
    """
    Abstract interface for Layer 3 AI moderation providers.
    """

    def __init__(self):
        self.call_count: int = 0

    @abstractmethod
    async def evaluate(self, user, text: str) -> ProviderResult:
        """
        Evaluate text for moderation violations asynchronously.
        """
        pass

    def reset_stats(self):
        self.call_count = 0


class NullProvider(BaseModerationProvider):
    """
    Default null provider that allows all content without delay.
    Matches current behavior prior to external AI integration.
    """

    async def evaluate(self, user, text: str) -> ProviderResult:
        self.call_count += 1
        return ProviderResult(
            verdict="allowed",
            latency_ms=0.0,
            flagged=False,
            reason="null_provider_pass",
        )


class MockProvider(BaseModerationProvider):
    """
    Mock provider with configurable simulated latency and ground truth rules.
    Used for benchmarks and tests without hitting paid external APIs.
    """

    def __init__(
        self,
        latency_ms: float = 0.0,
        default_verdict: str = "allowed",
        toxic_words: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.latency_ms = latency_ms
        self.default_verdict = default_verdict
        self.toxic_words = set(w.lower() for w in (toxic_words or []))

    async def evaluate(self, user, text: str) -> ProviderResult:
        self.call_count += 1
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        verdict = self.default_verdict
        reason = "mock_provider_default"

        if self.toxic_words:
            lower = text.lower()
            for w in self.toxic_words:
                if w in lower:
                    verdict = "blocked"
                    reason = f"matched_ground_truth_toxic_word: {w}"
                    break

        return ProviderResult(
            verdict=verdict,
            latency_ms=self.latency_ms,
            flagged=(verdict == "flagged"),
            reason=reason,
        )


def get_moderation_provider(name: Optional[str] = None) -> BaseModerationProvider:
    from django.conf import settings

    provider_name = (name or getattr(settings, "MODERATION_PROVIDER", "null")).lower()
    if provider_name == "mock":
        return MockProvider()
    return NullProvider()
