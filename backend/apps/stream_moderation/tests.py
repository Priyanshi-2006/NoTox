import math
import os
import warnings
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.chat.services import ChatService
from apps.stream_moderation.services import (
    AudioInterval,
    AudioIntervalModerator,
    FlaggedWordSegment,
    StreamModerationResult,
    StreamModerationService,
)

class StreamModerationServiceTests(SimpleTestCase):

    def test_clean_transcript_returns_unflagged_result(self):
        text = "Hello everyone, welcome to the stream today."
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.4},
            {"word": "everyone", "start": 0.5, "end": 0.9},
            {"word": "welcome", "start": 1.0, "end": 1.4},
        ]

        result = StreamModerationService.moderate_transcript(text, words)

        self.assertFalse(result.is_flagged)
        self.assertEqual(result.flagged_words, [])
        self.assertEqual(result.flagged_segments, [])
        self.assertEqual(result.original_text, text)

        data = result.to_dict()
        self.assertFalse(data["is_flagged"])
        self.assertEqual(data["flagged_segments"], [])

    def test_single_prohibited_word_with_valid_timestamps(self):
        # "damn" is in better-profanity's default CENSOR_WORDSET
        text = "What a damn mess"
        words = [
            {"word": "What", "start": 0.1, "end": 0.3},
            {"word": "a", "start": 0.35, "end": 0.4},
            {"word": "damn", "start": 0.45, "end": 0.8},
            {"word": "mess", "start": 0.85, "end": 1.1},
        ]

        result = StreamModerationService.moderate_transcript(text, words)

        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertEqual(len(result.flagged_segments), 1)

        seg = result.flagged_segments[0]
        self.assertEqual(seg.word, "damn")
        self.assertEqual(seg.start, 0.45)
        self.assertEqual(seg.end, 0.8)
        self.assertTrue(seg.has_valid_timing)

    def test_multiple_prohibited_words_with_timestamps(self):
        text = "This is damn loud and bullshit"
        words = [
            {"word": "This", "start": 0.0, "end": 0.2},
            {"word": "is", "start": 0.25, "end": 0.35},
            {"word": "damn", "start": 0.4, "end": 0.75},
            {"word": "loud", "start": 0.8, "end": 1.1},
            {"word": "and", "start": 1.15, "end": 1.25},
            {"word": "bullshit", "start": 1.3, "end": 1.8},
        ]


        result = StreamModerationService.moderate_transcript(text, words)

        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertIn("bullshit", result.flagged_words)
        self.assertEqual(len(result.flagged_segments), 2)

        first_seg = result.flagged_segments[0]
        self.assertEqual(first_seg.word, "damn")
        self.assertEqual(first_seg.start, 0.4)
        self.assertEqual(first_seg.end, 0.75)
        self.assertTrue(first_seg.has_valid_timing)

        second_seg = result.flagged_segments[1]
        self.assertEqual(second_seg.word, "bullshit")
        self.assertEqual(second_seg.start, 1.3)
        self.assertEqual(second_seg.end, 1.8)
        self.assertTrue(second_seg.has_valid_timing)

    def test_prohibited_word_with_missing_timestamps(self):
        text = "That is totally damn wrong"

        # words is None
        result_none = StreamModerationService.moderate_transcript(text, words=None)
        self.assertTrue(result_none.is_flagged)
        self.assertIn("damn", result_none.flagged_words)
        self.assertEqual(len(result_none.flagged_segments), 1)

        seg_none = result_none.flagged_segments[0]
        self.assertEqual(seg_none.word, "damn")
        self.assertIsNone(seg_none.start)
        self.assertIsNone(seg_none.end)
        self.assertFalse(seg_none.has_valid_timing)

        # words is provided but without start or end
        words_no_timing = [
            {"word": "That"},
            {"word": "is"},
            {"word": "totally"},
            {"word": "damn"},
            {"word": "wrong"},
        ]
        result_no_timing = StreamModerationService.moderate_transcript(text, words=words_no_timing)
        self.assertTrue(result_no_timing.is_flagged)
        self.assertIn("damn", result_no_timing.flagged_words)
        self.assertEqual(len(result_no_timing.flagged_segments), 1)

        seg_no_timing = result_no_timing.flagged_segments[0]
        self.assertEqual(seg_no_timing.word, "damn")
        self.assertIsNone(seg_no_timing.start)
        self.assertIsNone(seg_no_timing.end)
        self.assertFalse(seg_no_timing.has_valid_timing)

    def test_malformed_timestamps_are_safely_invalidated(self):
        text = "damn"

        malformed_cases = [
            # end <= start
            {"word": "damn", "start": 1.5, "end": 1.0},
            {"word": "damn", "start": 2.0, "end": 2.0},
            # negative values
            {"word": "damn", "start": -0.5, "end": 0.5},
            {"word": "damn", "start": 0.0, "end": -1.0},
            # non-finite floats
            {"word": "damn", "start": float("nan"), "end": 1.0},
            {"word": "damn", "start": 0.0, "end": float("inf")},
            # non-numeric strings
            {"word": "damn", "start": "invalid", "end": "also_invalid"},
            # None types
            {"word": "damn", "start": None, "end": 1.0},
            {"word": "damn", "start": 0.5, "end": None},
        ]

        for case in malformed_cases:
            with self.subTest(case=case):
                result = StreamModerationService.moderate_transcript(text, words=[case])
                self.assertTrue(result.is_flagged)
                self.assertIn("damn", result.flagged_words)
                self.assertEqual(len(result.flagged_segments), 1)

                seg = result.flagged_segments[0]
                self.assertEqual(seg.word, "damn")
                self.assertIsNone(seg.start)
                self.assertIsNone(seg.end)
                self.assertFalse(seg.has_valid_timing)

    def test_alternative_timestamp_field_names(self):
        text = "You are damn right"
        words = [
            {"word": "You", "start_time": 0.0, "end_time": 0.2},
            {"word": "are", "start_time": 0.25, "end_time": 0.4},
            {"word": "damn", "start_time": 0.45, "end_time": 0.85},
            {"word": "right", "start_time": 0.9, "end_time": 1.2},
        ]

        result = StreamModerationService.moderate_transcript(text, words=words)
        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertEqual(len(result.flagged_segments), 1)

        seg = result.flagged_segments[0]
        self.assertEqual(seg.word, "damn")
        self.assertEqual(seg.start, 0.45)
        self.assertEqual(seg.end, 0.85)
        self.assertTrue(seg.has_valid_timing)

    def test_malformed_word_objects_in_list_do_not_crash(self):
        text = "This is damn funny"
        words = [
            None,
            "not_a_dict",
            12345,
            {},
            {"no_word_key": "val"},
            {"word": None},
            {"word": "damn", "start": 0.5, "end": 0.9},
        ]

        result = StreamModerationService.moderate_transcript(text, words=words)
        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertEqual(len(result.flagged_segments), 1)
        self.assertEqual(result.flagged_segments[0].word, "damn")
        self.assertEqual(result.flagged_segments[0].start, 0.5)
        self.assertEqual(result.flagged_segments[0].end, 0.9)
        self.assertTrue(result.flagged_segments[0].has_valid_timing)

    def test_reuses_chat_service_contains_profanity(self):
        # Ensure ChatService.contains_profanity is explicitly invoked
        with patch.object(ChatService, "contains_profanity", wraps=ChatService.contains_profanity) as mock_mod:
            text = "Testing damn integration"
            words = [{"word": "damn", "start": 0.1, "end": 0.5}]

            result = StreamModerationService.moderate_transcript(text, words=words)

            self.assertTrue(result.is_flagged)
            self.assertTrue(mock_mod.called)
            # Verify called with the text and the word
            mock_mod.assert_any_call(text)
            mock_mod.assert_any_call("damn")

    def test_word_with_trailing_punctuation_is_moderated(self):
        text = "Oh damn! That was close."
        words = [
            {"word": "Oh", "start": 0.0, "end": 0.2},
            {"word": "damn!", "start": 0.25, "end": 0.6},
            {"word": "That", "start": 0.65, "end": 0.85},
        ]

        result = StreamModerationService.moderate_transcript(text, words=words)
        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertEqual(len(result.flagged_segments), 1)
        self.assertEqual(result.flagged_segments[0].word, "damn")
        self.assertEqual(result.flagged_segments[0].start, 0.25)
        self.assertEqual(result.flagged_segments[0].end, 0.6)
        self.assertTrue(result.flagged_segments[0].has_valid_timing)

    def test_empty_or_non_string_inputs_return_safe_defaults(self):
        for empty_val in ["", "   ", None, 12345]:
            with self.subTest(empty_val=empty_val):
                result = StreamModerationService.moderate_transcript(empty_val)
                self.assertFalse(result.is_flagged)
                self.assertEqual(result.flagged_words, [])
                self.assertEqual(result.flagged_segments, [])

    def test_wordlist_loading_from_settings(self):
        loaded = StreamModerationService.load_wordlist()
        self.assertTrue(loaded)
        self.assertTrue(StreamModerationService.contains_profanity("bastard"))
        self.assertTrue(StreamModerationService.contains_profanity("BASTARD"))
        self.assertTrue(StreamModerationService.contains_profanity("damn"))

    def test_load_wordlist_missing_file_falls_back_with_warning(self):
        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            loaded = StreamModerationService.load_wordlist(custom_path="/nonexistent/wordlist.txt")
            self.assertFalse(loaded)
            self.assertTrue(any("not found" in str(w.message) for w in recorded_warnings))
            # Fallback still flags default censor words like "damn"
            self.assertTrue(StreamModerationService.contains_profanity("damn"))
        # Restore normal wordlist
        StreamModerationService.load_wordlist()

    def test_custom_wordlist_temporary_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write("custombadword\nanotherbadterm\n")
            tmp_path = tmp.name

        try:
            loaded = StreamModerationService.load_wordlist(custom_path=tmp_path)
            self.assertTrue(loaded)
            self.assertTrue(StreamModerationService.contains_profanity("custombadword"))
            self.assertTrue(StreamModerationService.contains_profanity("anotherbadterm"))
            res = StreamModerationService.moderate_transcript("You are a custombadword now")
            self.assertTrue(res.is_flagged)
            self.assertIn("custombadword", res.flagged_words)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            StreamModerationService.load_wordlist()



class ModerateTranscriptApiTests(APITestCase):
    def setUp(self):
        self.url = reverse("stream-moderation-moderate")
        self.user = User.objects.create_user(
            username="streamer_alice",
            email="alice@example.com",
            password="StrongPass123!",
            display_name="Streamer Alice",
        )
        self.restricted_user = User.objects.create_user(
            username="restricted_bob",
            email="bob@example.com",
            password="StrongPass123!",
            is_restricted=True,
        )

    def _login(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_moderate_api_unauthenticated_returns_401(self):
        response = self.client.post(self.url, {"text": "hello world"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_moderate_api_restricted_user_returns_403(self):
        self._login(self.restricted_user)
        response = self.client.post(self.url, {"text": "hello world"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_moderate_api_clean_transcript_returns_200_unflagged(self):
        self._login(self.user)
        payload = {
            "text": "Welcome to my clean stream today",
            "words": [
                {"word": "Welcome", "start": 0.0, "end": 0.4},
                {"word": "to", "start": 0.45, "end": 0.6},
                {"word": "my", "start": 0.65, "end": 0.8},
                {"word": "clean", "start": 0.85, "end": 1.1},
                {"word": "stream", "start": 1.15, "end": 1.5},
                {"word": "today", "start": 1.55, "end": 1.8},
            ],
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_flagged"])
        self.assertEqual(response.data["flagged_words"], [])
        self.assertEqual(response.data["flagged_segments"], [])
        self.assertEqual(response.data["original_text"], payload["text"])

    def test_moderate_api_flagged_transcript_with_timestamps(self):
        self._login(self.user)
        payload = {
            "text": "What a damn mess",
            "words": [
                {"word": "What", "start": 0.1, "end": 0.3},
                {"word": "a", "start": 0.35, "end": 0.4},
                {"word": "damn", "start": 0.45, "end": 0.8},
                {"word": "mess", "start": 0.85, "end": 1.1},
            ],
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_flagged"])
        self.assertIn("damn", response.data["flagged_words"])
        self.assertEqual(len(response.data["flagged_segments"]), 1)
        seg = response.data["flagged_segments"][0]
        self.assertEqual(seg["word"], "damn")
        self.assertEqual(seg["start"], 0.45)
        self.assertEqual(seg["end"], 0.8)
        self.assertTrue(seg["has_valid_timing"])

    def test_moderate_api_missing_timestamps(self):
        self._login(self.user)
        payload = {"text": "That is totally damn wrong"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_flagged"])
        self.assertIn("damn", response.data["flagged_words"])
        self.assertEqual(len(response.data["flagged_segments"]), 1)
        seg = response.data["flagged_segments"][0]
        self.assertEqual(seg["word"], "damn")
        self.assertIsNone(seg["start"])
        self.assertIsNone(seg["end"])
        self.assertFalse(seg["has_valid_timing"])

    def test_moderate_api_missing_text_returns_400(self):
        self._login(self.user)
        response = self.client.post(self.url, {"words": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_moderate_api_non_string_text_returns_400(self):
        self._login(self.user)
        response = self.client.post(self.url, {"text": 12345}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_moderate_api_non_list_words_returns_400(self):
        self._login(self.user)
        response = self.client.post(self.url, {"text": "hello", "words": "not_a_list"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)


class AudioIntervalModeratorTests(SimpleTestCase):
    def setUp(self):
        self.moderator = AudioIntervalModerator(buffer_delay_sec=1.5, padding_sec=0.06)

    def test_profanity_detection_from_wordlist(self):
        profane_terms = ["fuck", "bastard", "bitch", "asshole", "bullshit"]
        for term in profane_terms:
            with self.subTest(term=term):
                self.assertTrue(
                    StreamModerationService.contains_profanity(term),
                    f"Expected wordlist to contain '{term}'"
                )
                res = StreamModerationService.moderate_transcript(f"This is totally {term} right now")
                self.assertTrue(res.is_flagged)
                self.assertIn(term, res.flagged_words)

    def test_clean_speech_not_flagged(self):
        # Innocent words like 'fall', 'flat', 'hello', 'class' must not be flagged
        clean_sentences = [
            "Hello everyone, welcome to the stream today.",
            "Watch out or you might fall on the flat floor.",
            "We are having a class discussion about physics.",
        ]
        for sentence in clean_sentences:
            with self.subTest(sentence=sentence):
                res = StreamModerationService.moderate_transcript(sentence)
                self.assertFalse(res.is_flagged)
                self.assertEqual(res.flagged_words, [])
                self.assertEqual(res.flagged_segments, [])

    def test_timestamp_to_audio_interval_mapping_preserves_clean_words(self):
        # Utterance: "hello fuck world"
        words = [
            {"word": "hello", "start": 0.2, "end": 0.6},
            {"word": "fuck", "start": 0.7, "end": 1.1},
            {"word": "world", "start": 1.2, "end": 1.6},
        ]
        result = StreamModerationService.moderate_transcript("hello fuck world", words=words)
        self.assertTrue(result.is_flagged)
        self.assertEqual(len(result.flagged_segments), 1)

        self.moderator.apply_moderation_result(
            words=words,
            flagged_segments=[s.to_dict() for s in result.flagged_segments]
        )

        # Profane interval [0.7 - 0.06, 1.1 + 0.06] must be suppressed
        suppress_at_fuck, reason_fuck = self.moderator.should_suppress_at_playout(
            stream_time=0.9, current_wall_time=5.0, registration_wall_time=3.0
        )
        self.assertTrue(suppress_at_fuck)
        self.assertEqual(reason_fuck, "censored_profanity")

        # Clean words [0.2, 0.6] and [1.2, 1.6] must NOT be suppressed
        suppress_at_hello, reason_hello = self.moderator.should_suppress_at_playout(
            stream_time=0.4, current_wall_time=5.0, registration_wall_time=3.0
        )
        self.assertFalse(suppress_at_hello)

        suppress_at_world, reason_world = self.moderator.should_suppress_at_playout(
            stream_time=1.4, current_wall_time=5.0, registration_wall_time=3.0
        )
        self.assertFalse(suppress_at_world)

    def test_audio_sample_suppression_produces_silence_for_profanity_only(self):
        sample_rate = 16000
        # 2 seconds of synthetic audio at unity amplitude 1.0
        samples = [1.0] * (sample_rate * 2)

        words = [
            {"word": "good", "start": 0.1, "end": 0.4},
            {"word": "fuck", "start": 0.6, "end": 1.0},
            {"word": "morning", "start": 1.2, "end": 1.6},
        ]
        result = StreamModerationService.moderate_transcript("good fuck morning", words=words)
        self.moderator.apply_moderation_result(
            words=words,
            flagged_segments=[s.to_dict() for s in result.flagged_segments]
        )

        censored_samples = self.moderator.censor_audio_samples(
            samples=samples,
            sample_rate=sample_rate,
            buffer_start_time=0.0,
            is_decision_late=False
        )

        # "good" at t = 0.2s is clean -> sample is 1.0
        sample_good = censored_samples[int(0.2 * sample_rate)]
        self.assertEqual(sample_good, 1.0)

        # "fuck" at t = 0.8s is censored -> sample is 0.0 (silence)
        sample_fuck = censored_samples[int(0.8 * sample_rate)]
        self.assertEqual(sample_fuck, 0.0)

        # "morning" at t = 1.4s is clean -> sample is 1.0
        sample_morning = censored_samples[int(1.4 * sample_rate)]
        self.assertEqual(sample_morning, 1.0)

    def test_delayed_moderation_decision_fails_closed(self):
        # Register speech interval from 2.0s to 3.0s
        self.moderator.register_speech_interval(start=2.0, end=3.0)

        # 1. While within buffer delay (decision not late yet): not suppressed yet
        suppress_early, reason_early = self.moderator.should_suppress_at_playout(
            stream_time=2.5,
            current_wall_time=10.5,
            registration_wall_time=10.0,  # 0.5s elapsed < 1.5s delay
        )
        self.assertFalse(suppress_early)
        self.assertEqual(reason_early, "buffering")

        # 2. Playout time arrives and decision has not arrived (delayed STT): FAIL CLOSED!
        suppress_late, reason_late = self.moderator.should_suppress_at_playout(
            stream_time=2.5,
            current_wall_time=12.0,
            registration_wall_time=10.0,  # 2.0s elapsed >= 1.5s delay
        )
        self.assertTrue(suppress_late)
        self.assertEqual(reason_late, "late_moderation_fail_closed")

    def test_delayed_moderation_decision_resolves_when_clean_arrives(self):
        self.moderator.register_speech_interval(start=2.0, end=3.0)

        # Moderation arrives confirming speech is clean
        clean_words = [{"word": "clean", "start": 2.0, "end": 2.5}, {"word": "speech", "start": 2.6, "end": 3.0}]
        self.moderator.apply_moderation_result(words=clean_words, flagged_segments=[])

        # Playout occurs after buffer delay: clean speech plays normally
        suppress, reason = self.moderator.should_suppress_at_playout(
            stream_time=2.5,
            current_wall_time=12.0,
            registration_wall_time=10.0,
        )
        self.assertFalse(suppress)
        self.assertEqual(reason, "clean_speech")
