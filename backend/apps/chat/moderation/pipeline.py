"""
Three-stage moderation pipeline:
Layer 1: Keyword filter
Layer 2: Bloom filter pre-check
Layer 3: AI moderation provider
"""

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from apps.chat.moderation.providers import BaseModerationProvider, get_moderation_provider

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(
    r"(https?://|www\.|\.([a-z]{2,6})/|[a-zA-Z0-9-]+\.(com|org|net|io|edu|gov|co|xyz|me)\b)",
    re.IGNORECASE,
)


@dataclass
class ModerationResult:
    stage: str           # "keyword", "bloom", "provider"
    verdict: str         # "allowed", "blocked", "flagged"
    bloom_status: str    # "clean", "uncertain"
    latency_ms: float
    audit_sampled: bool = False
    reason: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.verdict == "allowed"

    @property
    def is_blocked(self) -> bool:
        return self.verdict == "blocked"

    @property
    def is_flagged(self) -> bool:
        return self.verdict == "flagged"

    @property
    def is_clean(self) -> bool:
        return self.bloom_status == "clean"


class ModerationMetrics:
    """
    Thread-safe / event-loop counters for moderation monitoring.
    """

    def __init__(self):
        self.total_evaluated: int = 0
        self.layer1_keyword_blocks: int = 0
        self.fast_path_clean: int = 0
        self.layer2_uncertain: int = 0
        self.layer3_provider_calls: int = 0
        self.audit_samples: int = 0
        self.audit_disagreements: int = 0
        self.bloom_failures: int = 0
        self._last_bloom_failure_log: float = 0.0

    def record_bloom_failure(self, err_msg: str):
        self.bloom_failures += 1
        now = time.time()
        # Failures are counted and logged at most once a minute.
        if now - self._last_bloom_failure_log >= 60.0:
            logger.warning(
                "Bloom filter failure occurred (total failures=%d): %s",
                self.bloom_failures,
                err_msg,
            )
            self._last_bloom_failure_log = now

    def to_dict(self) -> dict:
        return {
            "total_evaluated": self.total_evaluated,
            "layer1_keyword_blocks": self.layer1_keyword_blocks,
            "fast_path_clean": self.fast_path_clean,
            "layer2_uncertain": self.layer2_uncertain,
            "layer3_provider_calls": self.layer3_provider_calls,
            "audit_samples": self.audit_samples,
            "audit_disagreements": self.audit_disagreements,
            "bloom_failures": self.bloom_failures,
        }

    def reset(self):
        self.total_evaluated = 0
        self.layer1_keyword_blocks = 0
        self.fast_path_clean = 0
        self.layer2_uncertain = 0
        self.layer3_provider_calls = 0
        self.audit_samples = 0
        self.audit_disagreements = 0
        self.bloom_failures = 0
        self._last_bloom_failure_log = 0.0


class ModerationPipeline:
    """
    Pipeline: Keyword Filter -> Bloom Pre-Check -> AI Provider
    """

    def __init__(
        self,
        bloom_backend=None,
        provider: Optional[BaseModerationProvider] = None,
        min_trust: Optional[int] = None,
        max_length: Optional[int] = None,
        audit_rate: Optional[float] = None,
        metrics: Optional[ModerationMetrics] = None,
    ):
        self._bloom_backend = bloom_backend
        self.provider = provider or get_moderation_provider()
        self.min_trust = (
            min_trust
            if min_trust is not None
            else getattr(settings, "BLOOM_MIN_TRUST", 80)
        )
        self.max_length = (
            max_length
            if max_length is not None
            else getattr(settings, "BLOOM_MAX_LENGTH", 500)
        )
        self.audit_rate = (
            audit_rate
            if audit_rate is not None
            else getattr(settings, "BLOOM_AUDIT_RATE", 0.05)
        )
        self.metrics = metrics or ModerationMetrics()

    @property
    def bloom_backend(self):
        if self._bloom_backend is None:
            from apps.chat.moderation.bloom import get_bloom_backend
            self._bloom_backend = get_bloom_backend()
        return self._bloom_backend

    def is_mostly_ascii(self, text: str, threshold: float = 0.8) -> bool:
        if not text:
            return True
        ascii_count = sum(1 for ch in text if ord(ch) < 128)
        return (ascii_count / len(text)) >= threshold

    def contains_url(self, text: str) -> bool:
        return bool(URL_REGEX.search(text))

    def is_eligible_for_fast_path(self, user, text: str, has_toxic_hit: bool) -> tuple[bool, str]:
        """
        Fast-path eligibility. 'Clean' is only honoured if all of these hold:
        1. No toxic-set hit.
        2. trust_score >= BLOOM_MIN_TRUST.
        3. No URL.
        4. Mostly ASCII (the SRS scopes to English).
        5. Within the length cap.
        Otherwise the message is treated as uncertain.
        """
        if has_toxic_hit:
            return False, "toxic_token_hit"

        user_trust = getattr(user, "trust_score", 100) if user else 0
        if user_trust < self.min_trust:
            return False, f"trust_score_below_minimum ({user_trust} < {self.min_trust})"

        if self.contains_url(text):
            return False, "contains_url"

        if not self.is_mostly_ascii(text):
            return False, "non_ascii_content"

        if len(text) > self.max_length:
            return False, f"length_exceeds_cap ({len(text)} > {self.max_length})"

        return True, "fast_path_clean"

    async def evaluate(self, user, text: str) -> ModerationResult:
        start_time = time.perf_counter()
        self.metrics.total_evaluated += 1

        # ------------------------------------------------------------------
        # Layer 1: Keyword filter (instant block, same as today)
        # ------------------------------------------------------------------
        from apps.chat.services import ChatService
        if ChatService.contains_profanity(text):
            self.metrics.layer1_keyword_blocks += 1
            latency = (time.perf_counter() - start_time) * 1000.0
            return ModerationResult(
                stage="keyword",
                verdict="blocked",
                bloom_status="uncertain",
                latency_ms=latency,
                reason="layer1_keyword_profanity",
            )

        # ------------------------------------------------------------------
        # Layer 2: Bloom filter pre-check
        # ------------------------------------------------------------------
        from apps.chat.moderation.tokenize import get_lookup_keys

        has_toxic_hit = False
        bloom_healthy = True

        try:
            lookup_keys = get_lookup_keys(text)
            has_toxic_hit = await self.bloom_backend.contains_any(lookup_keys)
        except Exception as exc:
            bloom_healthy = False
            self.metrics.record_bloom_failure(str(exc))
            has_toxic_hit = True  # fail-safe: treat as uncertain

        eligible, reason = self.is_eligible_for_fast_path(user, text, has_toxic_hit)

        if bloom_healthy and eligible:
            # Fast-path: clean message skips the provider call
            self.metrics.fast_path_clean += 1
            latency = (time.perf_counter() - start_time) * 1000.0

            # Audit sampling check
            audit_sampled = (random.random() < self.audit_rate)
            if audit_sampled:
                self.metrics.audit_samples += 1

            return ModerationResult(
                stage="bloom",
                verdict="allowed",
                bloom_status="clean",
                latency_ms=latency,
                audit_sampled=audit_sampled,
                reason=reason,
            )

        # ------------------------------------------------------------------
        # Layer 3: AI Moderation Provider (Uncertain message)
        # ------------------------------------------------------------------
        self.metrics.layer2_uncertain += 1
        self.metrics.layer3_provider_calls += 1

        provider_result = await self.provider.evaluate(user, text)
        latency = (time.perf_counter() - start_time) * 1000.0

        return ModerationResult(
            stage="provider",
            verdict=provider_result.verdict,
            bloom_status="uncertain",
            latency_ms=latency,
            reason=f"provider_eval: {provider_result.reason or reason}",
        )


_default_pipeline: Optional[ModerationPipeline] = None


def get_moderation_pipeline() -> ModerationPipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = ModerationPipeline()
    return _default_pipeline


def reset_moderation_pipeline():
    global _default_pipeline
    _default_pipeline = None
