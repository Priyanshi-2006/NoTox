"""
Three-stage moderation pipeline:
Layer 1: Keyword filter
Layer 2: Bloom filter pre-check
Layer 3: AI moderation provider (with optional contextual analysis)

The policy engine converts Layer 3 ContextualResult scores into a final
verdict (allow / flagged / blocked) using configurable thresholds.

Design invariants preserved:
- Fast-path eligibility rules are unchanged.
- Bloom filter safety guarantees are unchanged.
- Audit sampling behaviour is unchanged.
- Provider is only called for uncertain messages.
- Contextual analysis is only invoked for contextual-capable providers.
- Sarcasm alone never triggers a block.
- Low-confidence inferences do not modify trust scores.
"""

import logging
import math
import random
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from django.conf import settings

from apps.chat.moderation.providers import (
    BaseModerationProvider,
    ContextualResult,
    get_moderation_provider,
)

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
        self.contextual_analyses: int = 0
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
            "contextual_analyses": self.contextual_analyses,
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
        self.contextual_analyses = 0
        self._last_bloom_failure_log = 0.0


class ModerationPolicyEngine:
    """
    Converts a ContextualResult (produced by Layer 3) into a final verdict.

    The policy engine is the single place where score thresholds are
    applied.  All thresholds are configurable via Django settings so they
    can be tuned without code changes.

    Rules (applied in priority order):
    1. If the provider failed, preserve the existing fail-safe
       (allow, but log the failure).
    2. If threat_score >= POLICY_THREAT_BLOCK → BLOCK.
    3. If toxicity_score >= POLICY_TOXICITY_BLOCK → BLOCK.
    4. If harassment_score >= POLICY_HARASSMENT_BLOCK → BLOCK.
    5. If insult_score >= POLICY_HARASSMENT_BLOCK → BLOCK.
    6. If any score is in [POLICY_REVIEW_THRESHOLD, block_threshold) → REVIEW.
    7. Sarcasm alone never triggers a block (only informs reason_codes).
    8. Otherwise → ALLOW.
    """

    def __init__(
        self,
        toxicity_block: Optional[float] = None,
        threat_block: Optional[float] = None,
        harassment_block: Optional[float] = None,
        review_threshold: Optional[float] = None,
    ):
        self.toxicity_block = (
            toxicity_block
            if toxicity_block is not None
            else float(getattr(settings, "POLICY_TOXICITY_BLOCK", 0.85))
        )
        self.threat_block = (
            threat_block
            if threat_block is not None
            else float(getattr(settings, "POLICY_THREAT_BLOCK", 0.80))
        )
        self.harassment_block = (
            harassment_block
            if harassment_block is not None
            else float(getattr(settings, "POLICY_HARASSMENT_BLOCK", 0.80))
        )
        self.review_threshold = (
            review_threshold
            if review_threshold is not None
            else float(getattr(settings, "POLICY_REVIEW_THRESHOLD", 0.60))
        )

    def _finite(self, score: float) -> bool:
        return not math.isnan(score) and not math.isinf(score)

    def decide(self, ctx: ContextualResult) -> tuple:
        """
        Returns (verdict, reason) where:
        - verdict is "allowed", "blocked", or "flagged"
        - reason is a human-readable string for logging
        """
        if ctx.provider_failed:
            # Provider failure: do not block based on uncertainty.
            return "allowed", "provider_failed_fail_safe:" + ",".join(ctx.reason_codes)

        reason_parts = list(ctx.reason_codes)

        # Rule 2: threat
        if self._finite(ctx.threat_score) and ctx.threat_score >= self.threat_block:
            return "blocked", "policy_threat_block:" + ",".join(reason_parts)

        # Rule 3: toxicity
        if self._finite(ctx.toxicity_score) and ctx.toxicity_score >= self.toxicity_block:
            return "blocked", "policy_toxicity_block:" + ",".join(reason_parts)

        # Rule 4: harassment
        if (
            self._finite(ctx.harassment_score)
            and ctx.harassment_score >= self.harassment_block
        ):
            return "blocked", "policy_harassment_block:" + ",".join(reason_parts)

        # Rule 5: insult (same threshold as harassment)
        if (
            self._finite(ctx.insult_score)
            and ctx.insult_score >= self.harassment_block
        ):
            return "blocked", "policy_insult_block:" + ",".join(reason_parts)

        # Rule 6: review (any score in amber zone)
        scores_to_check = [
            ctx.toxicity_score, ctx.threat_score,
            ctx.harassment_score, ctx.insult_score,
        ]
        in_amber = any(
            self._finite(s) and s >= self.review_threshold
            for s in scores_to_check
        )
        if in_amber:
            # If only sarcasm pushed it over and confidence is low, stay at review.
            return "flagged", "policy_review:" + ",".join(reason_parts)

        # Rule 7: sarcasm alone → never block, never automatically flag.
        # Rule 8: allow.
        return "allowed", "policy_allow:" + ",".join(reason_parts)


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
        policy_engine: Optional[ModerationPolicyEngine] = None,
        context_window_size: Optional[int] = None,
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
        self.policy_engine = policy_engine or ModerationPolicyEngine()
        self.context_window_size = (
            context_window_size
            if context_window_size is not None
            else int(getattr(settings, "CONTEXT_WINDOW_SIZE", 5))
        )

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
        Fast-path eligibility.  'Clean' is only honoured if all of these hold:
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

    def _supports_contextual(self) -> bool:
        """
        Returns True when the current provider overrides evaluate_contextual
        beyond the base-class stub (i.e. it has real contextual analysis).
        """
        from apps.chat.moderation.providers import (
            GeminiProvider,
            HuggingFaceProvider,
            LocalTransformerProvider,
            MockProvider,
        )
        return isinstance(
            self.provider,
            (HuggingFaceProvider, LocalTransformerProvider, GeminiProvider, MockProvider),
        )

    async def _run_contextual_analysis(
        self,
        user,
        text: str,
        context: Optional[List[str]],
    ) -> tuple:
        """
        Run evaluate_contextual() and apply the policy engine.
        Returns (verdict, reason) strings.

        Errors are contained here; the pipeline's fail-safe (allow on failure)
        is handled by ContextualResult.provider_failed.
        """
        try:
            ctx: ContextualResult = await self.provider.evaluate_contextual(
                user, text, context
            )
            self.metrics.contextual_analyses += 1
        except Exception as exc:
            logger.warning(
                "Contextual analysis raised unexpectedly: %s", exc
            )
            from apps.chat.moderation.providers import _safe_contextual_result
            ctx = _safe_contextual_result(
                provider_failed=True,
                reason_codes=["contextual_exception"],
            )

        verdict, reason = self.policy_engine.decide(ctx)
        return verdict, reason

    async def evaluate(
        self,
        user,
        text: str,
        context: Optional[List[str]] = None,
    ) -> ModerationResult:
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

        if self._supports_contextual():
            # Use the richer contextual path with policy engine.
            verdict, policy_reason = await self._run_contextual_analysis(
                user, text, context
            )
            latency = (time.perf_counter() - start_time) * 1000.0
            return ModerationResult(
                stage="provider",
                verdict=verdict,
                bloom_status="uncertain",
                latency_ms=latency,
                reason=f"contextual_policy: {policy_reason}",
            )
        else:
            # Existing path: basic provider.evaluate() (NullProvider, etc.)
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
