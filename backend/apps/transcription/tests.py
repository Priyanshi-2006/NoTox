import json
import time
from unittest.mock import MagicMock, patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.stream_moderation.services import StreamModerationService
from apps.transcription.consumers import moderate_transcript_sync
from apps.transcription.engine import TranscriptionEngine
from config.asgi import application


def sync_get_access_token(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


@database_sync_to_async
def get_access_token(user):
    return sync_get_access_token(user)


class TranscriptionEngineUnitTests(SimpleTestCase):

    def test_missing_model_directory_raises_improperly_configured(self):
        TranscriptionEngine.reset_model()
        with patch.object(TranscriptionEngine, "get_model_path") as mock_path:
            mock_path.return_value.exists.return_value = False
            mock_path.return_value.is_dir.return_value = False

            with self.assertRaises(ImproperlyConfigured) as ctx:
                TranscriptionEngine.get_model()

            self.assertIn("Vosk model directory not found", str(ctx.exception))
        TranscriptionEngine.reset_model()

    def test_parse_recognition_json_valid_words_and_timestamps(self):
        sample_vosk_json = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.45, "end": 0.8, "word": "hello"},
                {"conf": 1.0, "start": 0.85, "end": 1.25, "word": "world"},
            ],
            "text": "hello world",
        })

        parsed = TranscriptionEngine.parse_recognition_json(sample_vosk_json)
        self.assertEqual(parsed["text"], "hello world")
        self.assertEqual(len(parsed["words"]), 2)

        self.assertEqual(parsed["words"][0]["word"], "hello")
        self.assertEqual(parsed["words"][0]["start"], 0.45)
        self.assertEqual(parsed["words"][0]["end"], 0.8)

        self.assertEqual(parsed["words"][1]["word"], "world")
        self.assertEqual(parsed["words"][1]["start"], 0.85)
        self.assertEqual(parsed["words"][1]["end"], 1.25)

    def test_parse_recognition_json_empty_or_malformed(self):
        self.assertEqual(TranscriptionEngine.parse_recognition_json(""), {"text": "", "words": []})
        self.assertEqual(TranscriptionEngine.parse_recognition_json("not-json"), {"text": "", "words": []})
        self.assertEqual(TranscriptionEngine.parse_recognition_json("{}"), {"text": "", "words": []})
        self.assertEqual(
            TranscriptionEngine.parse_recognition_json(json.dumps({"text": "", "result": []})),
            {"text": "", "words": []},
        )


class TranscriptionConsumerWebSocketTests(TransactionTestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="speaker_alice",
            email="speaker_alice@example.com",
            password="StrongPass123!",
            display_name="Speaker Alice",
        )
        self.restricted_user = User.objects.create_user(
            username="restricted_speaker",
            email="restricted_speaker@example.com",
            password="StrongPass123!",
            is_restricted=True,
        )

    async def _authenticate_communicator(self, communicator, user):
        token = await get_access_token(user)
        # Receive auth_required
        auth_req = await communicator.receive_json_from()
        self.assertEqual(auth_req["type"], "auth_required")

        # Send authenticate message
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        auth_resp = await communicator.receive_json_from()
        self.assertEqual(auth_resp["type"], "authenticated")
        self.assertEqual(auth_resp["username"], user.username)

    async def test_connect_sends_auth_required(self):
        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        event = await communicator.receive_json_from()
        self.assertEqual(event["type"], "auth_required")
        await communicator.disconnect()

    async def test_binary_audio_before_auth_closes_4401(self):
        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        # Send binary bytes without authenticating first
        fake_pcm = b"\x00\x00" * 160
        await communicator.send_to(bytes_data=fake_pcm)

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4401)

    async def test_invalid_token_closes_4401(self):
        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        await communicator.send_json_to({
            "type": "authenticate",
            "token": "invalid.jwt.token",
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4401)

    async def test_non_authenticate_message_closes_4401(self):
        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        await communicator.send_json_to({
            "type": "chat",
            "message": "hello",
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4401)

    async def test_restricted_user_closes_4403(self):
        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.restricted_user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4403)

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_authenticated_binary_audio_emits_transcript(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.AcceptWaveform.return_value = True
        mock_rec.Result.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.2, "end": 0.6, "word": "testing"},
                {"conf": 1.0, "start": 0.65, "end": 1.1, "word": "audio"},
            ],
            "text": "testing audio",
        })
        mock_create_rec.return_value = mock_rec

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        # Send 160 samples (320 bytes) of 16kHz 16-bit mono PCM
        pcm_bytes = b"\x00\x00" * 160
        await communicator.send_to(bytes_data=pcm_bytes)

        # Expect transcript message
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "transcript")
        self.assertTrue(response["is_final"])
        self.assertEqual(response["text"], "testing audio")
        self.assertEqual(len(response["words"]), 2)
        self.assertEqual(response["words"][0]["word"], "testing")
        self.assertEqual(response["words"][0]["start"], 0.2)
        self.assertEqual(response["words"][0]["end"], 0.6)

        await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_oversized_audio_chunk_returns_error(self, mock_create_rec):
        mock_create_rec.return_value = MagicMock()

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        # Send chunk exceeding 64 KB (e.g. 65 KB)
        oversized_pcm = b"\x00" * (65 * 1024)
        await communicator.send_to(bytes_data=oversized_pcm)

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "error")
        self.assertIn("exceeds maximum allowed size", response["message"])

        await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_odd_length_pcm_chunk_returns_error(self, mock_create_rec):
        mock_create_rec.return_value = MagicMock()

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        # Send odd number of bytes (e.g. 3 bytes, invalid for 16-bit PCM)
        odd_pcm = b"\x00\x00\x00"
        await communicator.send_to(bytes_data=odd_pcm)

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "error")
        self.assertIn("odd byte length", response["message"])

        await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_finalize_control_message_flushes_final_transcript(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.FinalResult.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 1.0, "end": 1.4, "word": "done"},
            ],
            "text": "done",
        })
        mock_create_rec.return_value = mock_rec

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        # Send finalize command
        await communicator.send_json_to({"type": "finalize"})

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "transcript")
        self.assertTrue(response["is_final"])
        self.assertEqual(response["text"], "done")
        self.assertEqual(len(response["words"]), 1)
        self.assertEqual(response["words"][0]["word"], "done")

        await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_authenticated_binary_audio_normal_transcript_moderation(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.AcceptWaveform.return_value = True
        mock_rec.Result.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.2, "end": 0.6, "word": "testing"},
                {"conf": 1.0, "start": 0.65, "end": 1.1, "word": "audio"},
            ],
            "text": "testing audio",
        })
        mock_create_rec.return_value = mock_rec

        moderation_results = []
        orig_moderate = StreamModerationService.moderate_transcript

        def spy_moderate(*args, **kwargs):
            res = orig_moderate(*args, **kwargs)
            moderation_results.append(res)
            return res

        with patch.object(StreamModerationService, "moderate_transcript", side_effect=spy_moderate) as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            pcm_bytes = b"\x00\x00" * 160
            await communicator.send_to(bytes_data=pcm_bytes)

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "transcript")
            self.assertEqual(response["text"], "testing audio")
            self.assertFalse(response.get("censor"))
            self.assertIsNotNone(response.get("moderation"))
            self.assertFalse(response["moderation"]["is_flagged"])

            self.assertEqual(mock_moderate.call_count, 1)
            self.assertEqual(len(moderation_results), 1)
            result = moderation_results[0]
            self.assertFalse(result.is_flagged)
            self.assertEqual(result.flagged_words, [])
            self.assertEqual(result.flagged_segments, [])

            await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_authenticated_binary_audio_prohibited_transcript_moderation(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.AcceptWaveform.return_value = True
        mock_rec.Result.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.1, "end": 0.3, "word": "what"},
                {"conf": 1.0, "start": 0.35, "end": 0.4, "word": "a"},
                {"conf": 1.0, "start": 0.45, "end": 0.8, "word": "damn"},
                {"conf": 1.0, "start": 0.85, "end": 1.1, "word": "mess"},
            ],
            "text": "what a damn mess",
        })
        mock_create_rec.return_value = mock_rec

        moderation_results = []
        orig_moderate = StreamModerationService.moderate_transcript

        def spy_moderate(*args, **kwargs):
            res = orig_moderate(*args, **kwargs)
            moderation_results.append(res)
            return res

        with patch.object(StreamModerationService, "moderate_transcript", side_effect=spy_moderate) as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            pcm_bytes = b"\x00\x00" * 160
            await communicator.send_to(bytes_data=pcm_bytes)

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "transcript")
            self.assertEqual(response["text"], "what a damn mess")
            self.assertTrue(response.get("censor"))
            self.assertIsNotNone(response.get("moderation"))
            self.assertTrue(response["moderation"]["is_flagged"])
            self.assertIn("damn", response["moderation"]["flagged_words"])

            self.assertEqual(mock_moderate.call_count, 1)
            self.assertEqual(len(moderation_results), 1)
            result = moderation_results[0]
            self.assertTrue(result.is_flagged)
            self.assertIn("damn", result.flagged_words)
            self.assertEqual(len(result.flagged_segments), 1)
            seg = result.flagged_segments[0]
            self.assertEqual(seg.word, "damn")
            self.assertEqual(seg.start, 0.45)
            self.assertEqual(seg.end, 0.8)
            self.assertTrue(seg.has_valid_timing)

            await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_authenticated_audio_with_profanity_wordlist_triggers_censor(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.AcceptWaveform.return_value = True
        mock_rec.Result.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.2, "end": 0.7, "word": "bastard"},
            ],
            "text": "bastard",
        })
        mock_create_rec.return_value = mock_rec

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        pcm_bytes = b"\x00\x00" * 160
        await communicator.send_to(bytes_data=pcm_bytes)

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "transcript")
        self.assertEqual(response["text"], "bastard")
        self.assertTrue(response.get("censor"))
        self.assertIsNotNone(response.get("moderation"))
        self.assertTrue(response["moderation"]["is_flagged"])
        self.assertIn("bastard", response["moderation"]["flagged_words"])

        await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_finalize_control_message_normal_transcript_moderation(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.FinalResult.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 1.0, "end": 1.4, "word": "goodbye"},
            ],
            "text": "goodbye",
        })
        mock_create_rec.return_value = mock_rec

        moderation_results = []
        orig_moderate = StreamModerationService.moderate_transcript

        def spy_moderate(*args, **kwargs):
            res = orig_moderate(*args, **kwargs)
            moderation_results.append(res)
            return res

        with patch.object(StreamModerationService, "moderate_transcript", side_effect=spy_moderate) as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            await communicator.send_json_to({"type": "finalize"})

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "transcript")
            self.assertEqual(response["text"], "goodbye")

            self.assertEqual(mock_moderate.call_count, 1)
            self.assertEqual(len(moderation_results), 1)
            result = moderation_results[0]
            self.assertFalse(result.is_flagged)
            self.assertEqual(result.flagged_words, [])

            await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_finalize_control_message_prohibited_transcript_moderation(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.FinalResult.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.5, "end": 0.8, "word": "that"},
                {"conf": 1.0, "start": 0.85, "end": 1.0, "word": "is"},
                {"conf": 1.0, "start": 1.05, "end": 1.5, "word": "bullshit"},
            ],
            "text": "that is bullshit",
        })
        mock_create_rec.return_value = mock_rec

        moderation_results = []
        orig_moderate = StreamModerationService.moderate_transcript

        def spy_moderate(*args, **kwargs):
            res = orig_moderate(*args, **kwargs)
            moderation_results.append(res)
            return res

        with patch.object(StreamModerationService, "moderate_transcript", side_effect=spy_moderate) as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            await communicator.send_json_to({"type": "finalize"})

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "transcript")
            self.assertEqual(response["text"], "that is bullshit")

            self.assertEqual(mock_moderate.call_count, 1)
            self.assertEqual(len(moderation_results), 1)
            result = moderation_results[0]
            self.assertTrue(result.is_flagged)
            self.assertIn("bullshit", result.flagged_words)
            self.assertEqual(len(result.flagged_segments), 1)
            seg = result.flagged_segments[0]
            self.assertEqual(seg.word, "bullshit")
            self.assertEqual(seg.start, 1.05)
            self.assertEqual(seg.end, 1.5)
            self.assertTrue(seg.has_valid_timing)

            await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_finalize_control_message_empty_text_does_not_moderate_or_emit(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.FinalResult.return_value = json.dumps({
            "result": [],
            "text": "",
        })
        mock_create_rec.return_value = mock_rec

        with patch.object(StreamModerationService, "moderate_transcript") as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            await communicator.send_json_to({"type": "finalize"})

            self.assertTrue(await communicator.receive_nothing())
            mock_moderate.assert_not_called()

            await communicator.disconnect()

    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_flush_control_message_prohibited_transcript_moderation(self, mock_create_rec):
        mock_rec = MagicMock()
        mock_rec.FinalResult.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.2, "end": 0.6, "word": "damn"},
            ],
            "text": "damn",
        })
        mock_create_rec.return_value = mock_rec

        moderation_results = []
        orig_moderate = StreamModerationService.moderate_transcript

        def spy_moderate(*args, **kwargs):
            res = orig_moderate(*args, **kwargs)
            moderation_results.append(res)
            return res

        with patch.object(StreamModerationService, "moderate_transcript", side_effect=spy_moderate) as mock_moderate:
            communicator = WebsocketCommunicator(application, "/ws/transcription/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await self._authenticate_communicator(communicator, self.user)

            await communicator.send_json_to({"type": "flush"})

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "transcript")
            self.assertEqual(response["text"], "damn")

            self.assertEqual(mock_moderate.call_count, 1)
            self.assertEqual(len(moderation_results), 1)
            result = moderation_results[0]
            self.assertTrue(result.is_flagged)
            self.assertIn("damn", result.flagged_words)

            await communicator.disconnect()

    @patch.object(StreamModerationService, "moderate_transcript", side_effect=RuntimeError("temporary moderation failure"))
    @patch("apps.transcription.engine.TranscriptionEngine.create_recognizer")
    async def test_moderation_service_exception_does_not_crash_consumer(self, mock_create_rec, mock_moderate):
        mock_rec = MagicMock()
        mock_rec.AcceptWaveform.return_value = True
        mock_rec.Result.return_value = json.dumps({
            "result": [
                {"conf": 1.0, "start": 0.1, "end": 0.4, "word": "speech"},
            ],
            "text": "speech",
        })
        mock_rec.FinalResult.return_value = json.dumps({"text": "", "result": []})
        mock_create_rec.return_value = mock_rec

        communicator = WebsocketCommunicator(application, "/ws/transcription/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._authenticate_communicator(communicator, self.user)

        pcm_bytes = b"\x00\x00" * 160
        await communicator.send_to(bytes_data=pcm_bytes)

        # Transcript is still delivered despite moderation exception
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "transcript")
        self.assertEqual(response["text"], "speech")

        # Connection remains responsive
        await communicator.send_json_to({"type": "finalize"})
        self.assertTrue(await communicator.receive_nothing())

        await communicator.disconnect()

    async def test_moderate_transcript_sync_helper(self):
        words = [{"word": "damn", "start": 0.1, "end": 0.5}]
        result = await moderate_transcript_sync("damn", words)
        self.assertTrue(result.is_flagged)
        self.assertIn("damn", result.flagged_words)
        self.assertEqual(result.flagged_segments[0].word, "damn")
