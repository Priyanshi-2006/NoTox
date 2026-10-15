"""
Unit and property tests for Chat Moderation Layer 2:
- Normalization variants (NFKC, zero-width, repeats collapse, de-leet, spaced letters)
- Tokenization (unigrams and bigrams)
- LocalBloomBackend (sizing, capacity, zero false negatives)
- Property test: every seeded token is found in the filter
- Invariant: adding a normalization variant never turns 'uncertain' into 'clean'
- Pipeline fast-path eligibility and fail-safe guards
- Provider call counts
"""

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.chat.moderation.bloom import (
    LocalBloomBackend,
    RedisBloomBackend,
    calculate_bloom_dimensions,
)
from apps.chat.moderation.normalize import (
    collapse_long_repeats,
    de_leet,
    generate_text_variants,
    join_spaced_letters,
    nfkc_normalize,
    strip_zero_width,
)
from apps.chat.moderation.pipeline import ModerationPipeline, ModerationResult
from apps.chat.moderation.providers import MockProvider, NullProvider
from apps.chat.moderation.seed import load_seed_tokens, seed_bloom
from apps.chat.moderation.tokenize import extract_tokens, get_lookup_keys


class SizingAndMathTests(SimpleTestCase):
    def test_calculate_bloom_dimensions_50k(self):
        # n = 50,000, p = 0.001 -> ~90 KB and k ~ 10
        m, k = calculate_bloom_dimensions(50000, 0.001)
        self.assertEqual(k, 10)
        self.assertAlmostEqual(m / 8 / 1024, 87.76, delta=2.5)  # ~88-90 KB

    def test_calculate_bloom_dimensions_invalid(self):
        with self.assertRaises(ValueError):
            calculate_bloom_dimensions(0, 0.01)
        with self.assertRaises(ValueError):
            calculate_bloom_dimensions(1000, 1.5)


class NormalizationTests(SimpleTestCase):
    def test_nfkc_normalization(self):
        fullwidth = "ｆｕｃｋ"
        self.assertEqual(nfkc_normalize(fullwidth), "fuck")

    def test_strip_zero_width(self):
        hidden = "f\u200bu\u200cc\u200dk\ufeff"
        self.assertEqual(strip_zero_width(hidden), "fuck")

    def test_collapse_long_repeats(self):
        repeats = "fuuuuck sooooo biiiitch"
        collapsed = collapse_long_repeats(repeats)
        self.assertEqual(collapsed, "fuck so bitch")

    def test_de_leet(self):
        leeted = "b1tch sh!t 4ss"
        self.assertEqual(de_leet(leeted), "bitch shit ass")

    def test_join_spaced_letters(self):
        spaced = "f u c k this conversation"
        joined = join_spaced_letters(spaced)
        self.assertEqual(joined, "fuck this conversation")

    def test_generate_text_variants_contains_all_forms(self):
        text = "f\u200b u u u c k"
        variants = generate_text_variants(text)
        self.assertTrue(any("fuck" in v for v in variants))


class TokenizationTests(SimpleTestCase):
    def test_extract_tokens_unigrams(self):
        tokens = extract_tokens("Hello, beautiful world!")
        self.assertEqual(tokens, ["Hello", "beautiful", "world"])

    def test_get_lookup_keys_unigrams_and_bigrams(self):
        keys = get_lookup_keys("clean message today")
        self.assertIn("clean", keys)
        self.assertIn("message", keys)
        self.assertIn("today", keys)
        self.assertIn("clean message", keys)
        self.assertIn("message today", keys)

    def test_obfuscated_variants_added_to_keys(self):
        keys = get_lookup_keys("f u c k")
        self.assertIn("fuck", keys)

        keys_leet = get_lookup_keys("b1tch")
        self.assertIn("bitch", keys_leet)


class LocalBloomBackendTests(SimpleTestCase):
    async def test_add_and_contains(self):
        bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)
        await bloom.add("toxic_token")
        self.assertTrue(await bloom.contains("toxic_token"))
        self.assertFalse(await bloom.contains("innocent_token"))

    async def test_contains_any(self):
        bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)
        await bloom.add("badword")
        self.assertTrue(await bloom.contains_any(["hello", "world", "badword"]))
        self.assertFalse(await bloom.contains_any(["hello", "world", "good"]))

    async def test_clear(self):
        bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)
        await bloom.add("badword")
        self.assertTrue(await bloom.contains("badword"))
        await bloom.clear()
        self.assertFalse(await bloom.contains("badword"))


class PropertyAndInvariantTests(SimpleTestCase):
    async def test_property_every_seeded_token_is_found_in_filter(self):
        """
        Property test: every seeded token is found in the filter.
        Zero false negatives on the seeded toxic set.
        """
        bloom = LocalBloomBackend(capacity=50000, error_rate=0.001)
        seed_tokens = load_seed_tokens()
        self.assertGreater(len(seed_tokens), 0)

        await bloom.add_many(seed_tokens)

        # Check every single seeded token
        missing = []
        for token in seed_tokens:
            if not await bloom.contains(token):
                missing.append(token)

        self.assertEqual(missing, [], f"Missing {len(missing)} seeded tokens in Bloom filter!")

    async def test_invariant_adding_variant_never_turns_uncertain_into_clean(self):
        """
        Invariant: adding a normalization variant only adds lookup keys, never removes them.
        Extra variants can only raise the 'uncertain' rate, never lower it.
        """
        bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)
        await bloom.add("toxic")

        # Base text with toxic key
        base_keys = get_lookup_keys("this is toxic")
        self.assertTrue(await bloom.contains_any(base_keys))

        # Text with additional variants / obfuscation
        obfuscated_keys = get_lookup_keys("this is t0x1c with f u c k")
        self.assertTrue(await bloom.contains_any(obfuscated_keys))

        # Adding variants can only enlarge the key set
        self.assertTrue(len(obfuscated_keys) >= len(extract_tokens("this is t0x1c with f u c k")))


class PipelineGuardsAndCallCountTests(TestCase):
    def setUp(self):
        self.trusted_user = User.objects.create_user(
            username="trusted_alice",
            email="trusted@example.com",
            password="StrongPass123!",
            trust_score=100,
        )
        self.low_trust_user = User.objects.create_user(
            username="low_bob",
            email="low@example.com",
            password="StrongPass123!",
            trust_score=50,  # below default BLOOM_MIN_TRUST=80
        )
        self.bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)
        self.mock_provider = MockProvider(toxic_words={"badphrase"})
        self.pipeline = ModerationPipeline(
            bloom_backend=self.bloom,
            provider=self.mock_provider,
            min_trust=80,
            max_length=200,
            audit_rate=0.0,  # disable audit for call-count deterministic tests
        )

    async def test_clean_message_zero_provider_calls(self):
        """
        Clean message with trusted user -> fast-path honoured, 0 provider calls.
        """
        self.mock_provider.reset_stats()
        result = await self.pipeline.evaluate(self.trusted_user, "Hello how are you today")

        self.assertEqual(result.stage, "bloom")
        self.assertEqual(result.verdict, "allowed")
        self.assertEqual(result.bloom_status, "clean")
        self.assertEqual(self.mock_provider.call_count, 0)

    async def test_toxic_token_message_calls_provider_once(self):
        """
        Toxic-token hit in Bloom filter -> 1 provider call.
        """
        await self.bloom.add("badphrase")
        self.mock_provider.reset_stats()

        result = await self.pipeline.evaluate(self.trusted_user, "This contains badphrase here")

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_low_trust_user_never_fast_pathed(self):
        """
        Low-trust user (trust_score < BLOOM_MIN_TRUST) is never fast-pathed.
        Treated as uncertain and sent to provider.
        """
        self.mock_provider.reset_stats()
        result = await self.pipeline.evaluate(self.low_trust_user, "Clean message from untrusted user")

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_message_with_url_treated_as_uncertain(self):
        self.mock_provider.reset_stats()
        result = await self.pipeline.evaluate(self.trusted_user, "Check out https://example.com for more info")

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_message_exceeding_length_cap_treated_as_uncertain(self):
        self.mock_provider.reset_stats()
        long_message = "hello " * 45  # > 200 characters
        result = await self.pipeline.evaluate(self.trusted_user, long_message)

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_non_ascii_message_treated_as_uncertain(self):
        self.mock_provider.reset_stats()
        non_ascii_message = "Привет мир, это русский текст для проверки модерации"
        result = await self.pipeline.evaluate(self.trusted_user, non_ascii_message)

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_layer1_keyword_blocks_immediately_without_calling_provider(self):
        """
        Layer 1 keyword filter blocks immediately with 0 provider calls.
        """
        self.mock_provider.reset_stats()
        # "fuck" is a default profanity word
        result = await self.pipeline.evaluate(self.trusted_user, "fuck this")

        self.assertEqual(result.stage, "keyword")
        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(self.mock_provider.call_count, 0)


class FailSafeAndRedisTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="failsafe_user",
            email="failsafe@example.com",
            password="StrongPass123!",
            trust_score=100,
        )
        self.mock_provider = MockProvider(toxic_words={"danger"})

    async def test_throwing_backend_still_calls_provider_and_marks_uncertain(self):
        """
        Fail-safe: If Bloom backend throws, result is 'uncertain' and provider is called.
        No moderation coverage is lost.
        """
        throwing_backend = AsyncMock()
        throwing_backend.contains_any.side_effect = RuntimeError("Redis connection broken")

        pipeline = ModerationPipeline(
            bloom_backend=throwing_backend,
            provider=self.mock_provider,
        )
        self.mock_provider.reset_stats()

        # Message contains toxic word known by provider
        result = await pipeline.evaluate(self.user, "This has danger inside")

        self.assertEqual(result.stage, "provider")
        self.assertEqual(result.bloom_status, "uncertain")
        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(self.mock_provider.call_count, 1)
        self.assertEqual(pipeline.metrics.bloom_failures, 1)

    async def test_bloom_failure_logged_at_most_once_per_minute(self):
        """
        Failures are counted and logged at most once a minute.
        """
        throwing_backend = AsyncMock()
        throwing_backend.contains_any.side_effect = RuntimeError("Redis down")

        pipeline = ModerationPipeline(
            bloom_backend=throwing_backend,
            provider=self.mock_provider,
        )

        with patch("apps.chat.moderation.pipeline.logger.warning") as mock_warn:
            for _ in range(5):
                await pipeline.evaluate(self.user, "Hello test message")

            self.assertEqual(pipeline.metrics.bloom_failures, 5)
            # Logger warning should be called exactly once despite 5 failures within seconds
            self.assertEqual(mock_warn.call_count, 1)

    async def test_redis_capability_probe_offline(self):
        """
        Capability probe safely returns False when Redis/Memurai is not running.
        """
        # Port 63999 is guaranteed closed
        redis_backend = RedisBloomBackend(port=63999, timeout_ms=50)
        healthy = await redis_backend.probe()
        self.assertFalse(healthy)

    async def test_redis_backend_contains_any_mocked(self):
        """
        RedisBloomBackend sends single BF.MEXISTS round trip and interprets boolean array.
        """
        redis_backend = RedisBloomBackend(timeout_ms=100)
        mock_client = AsyncMock()
        # BF.MEXISTS returns [0, 1, 0] -> at least one match
        mock_client.execute_command.return_value = [0, 1, 0]

        with patch.object(redis_backend, "get_client", return_value=mock_client):
            has_hit = await redis_backend.contains_any(["apple", "banana", "toxic"])
            self.assertTrue(has_hit)
            mock_client.execute_command.assert_awaited_once_with(
                "BF.MEXISTS",
                redis_backend.key,
                "apple",
                "banana",
                "toxic",
            )


class AuditSamplingAndMetricsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="audit_tester",
            email="audit@example.com",
            password="StrongPass123!",
            trust_score=100,
        )
        self.bloom = LocalBloomBackend(capacity=1000, error_rate=0.001)

    async def test_audit_rate_sampling(self):
        # 100% audit rate
        pipeline = ModerationPipeline(
            bloom_backend=self.bloom,
            provider=NullProvider(),
            audit_rate=1.0,
        )

        res = await pipeline.evaluate(self.user, "Nice friendly clean post")
        self.assertEqual(res.stage, "bloom")
        self.assertEqual(res.bloom_status, "clean")
        self.assertTrue(res.audit_sampled)
        self.assertEqual(pipeline.metrics.audit_samples, 1)

    async def test_audit_disagreement_detection_via_consumer_helper(self):
        # Mock provider flags "stealth_toxic", which is not in the bloom filter
        mock_provider = MockProvider(toxic_words={"stealth_toxic"})
        pipeline = ModerationPipeline(
            bloom_backend=self.bloom,
            provider=mock_provider,
            audit_rate=1.0,
        )

        from apps.chat.consumers import GlobalChatConsumer
        consumer = GlobalChatConsumer()

        # Bloom thinks it's clean
        mod_result = await pipeline.evaluate(self.user, "This contains stealth_toxic inside")
        self.assertEqual(mod_result.stage, "bloom")
        self.assertEqual(mod_result.bloom_status, "clean")

        # Run async audit check
        with patch.object(consumer, "log_moderation_event", new_callable=AsyncMock) as mock_log:
            await consumer.run_audit_check(pipeline, self.user, None, "This contains stealth_toxic inside")
            self.assertEqual(pipeline.metrics.audit_disagreements, 1)
            mock_log.assert_awaited_once()
            called_mod = mock_log.await_args[0][2]
            self.assertEqual(called_mod.stage, "audit")
            self.assertEqual(called_mod.verdict, "blocked")

