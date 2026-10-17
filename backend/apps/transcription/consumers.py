import json
import time
from typing import Any, Optional

from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.exceptions import ImproperlyConfigured

from apps.chat.authentication import check_user_restriction, get_user_from_token
from apps.transcription.engine import TranscriptionEngine
from apps.stream_moderation.services import StreamModerationService


from channels.db import database_sync_to_async


@database_sync_to_async
def moderate_transcript_sync(text, words):
    return StreamModerationService.moderate_transcript(
        text=text,
        words=words,
    )


# Maximum chunk size: 64 KB (~2 seconds of 16kHz 16-bit mono PCM)
MAX_AUDIO_CHUNK_SIZE_BYTES = 64 * 1024


class TranscriptionConsumer(AsyncWebsocketConsumer):
    """
    Dedicated WebSocket consumer for live-stream speech-to-text.
    Accepts 16 kHz mono signed 16-bit PCM binary audio chunks from authenticated users
    and emits finalized transcripts with word-level start/end timestamps.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: Optional[Any] = None
        self.token_exp: Optional[float] = None
        self.is_authenticated: bool = False
        self.recognizer: Optional[Any] = None

    async def connect(self):
        await self.accept()
        # In-band authentication handshake (matching GlobalChatConsumer)
        await self.send(
            text_data=json.dumps({
                "type": "auth_required",
                "message": "Send your access token to authenticate.",
            })
        )

    async def disconnect(self, close_code):
        # Explicitly release recognizer instance to free Kaldi lattice memory
        self.recognizer = None
        self.is_authenticated = False

    async def _handle_finalized_transcript(
        self, raw_result: str, log_prefix: str = "[NoTox Moderation]"
    ) -> Optional[Any]:
        parsed = TranscriptionEngine.parse_recognition_json(raw_result)
        text = parsed.get("text", "").strip()
        if not text:
            return None

        words = parsed.get("words", [])

        moderation = None
        try:
            moderation = await moderate_transcript_sync(
                text=text,
                words=words,
            )
            print(log_prefix, moderation.to_dict())
        except Exception as exc:
            print(f"{log_prefix} Error during moderation: {exc}")

        moderation_dict = moderation.to_dict() if moderation else None
        is_flagged = bool(moderation and moderation.is_flagged)

        try:
            await self.send(
                text_data=json.dumps({
                    "type": "transcript",
                    "is_final": True,
                    "text": text,
                    "words": words,
                    "moderation": moderation_dict,
                    "censor": is_flagged,
                })
            )
        except Exception as exc:
            print(f"{log_prefix} Could not dispatch transcript: {exc}")

        return moderation

    async def receive(self, text_data=None, bytes_data=None):
        # 1. Enforce authentication prior to processing any audio or commands
        if not self.is_authenticated:
            if bytes_data is not None:
                # Binary audio received before authentication is strictly forbidden
                await self.close(code=4401)
                return

            if text_data is None:
                await self.close(code=4401)
                return

            try:
                auth_payload = json.loads(text_data)
            except (json.JSONDecodeError, TypeError):
                await self.close(code=4401)
                return

            if not isinstance(auth_payload, dict) or auth_payload.get("type") != "authenticate":
                await self.close(code=4401)
                return

            token = auth_payload.get("token")
            if not isinstance(token, str) or not token.strip():
                await self.close(code=4401)
                return

            user, token_exp, is_restricted = await get_user_from_token(token.strip())
            if user is None:
                await self.close(code=4401)
                return

            if is_restricted:
                await self.close(code=4403)
                return

            # Initialize the per-connection Vosk recognizer
            try:
                self.recognizer = TranscriptionEngine.create_recognizer(sample_rate=16000.0)
            except ImproperlyConfigured as exc:
                await self.send(
                    text_data=json.dumps({
                        "type": "error",
                        "message": str(exc),
                    })
                )
                await self.close(code=4500)
                return

            self.user = user
            self.token_exp = token_exp
            self.is_authenticated = True

            await self.send(
                text_data=json.dumps({
                    "type": "authenticated",
                    "username": user.username,
                })
            )
            return

        # 2. Token expiration check
        if self.token_exp is not None and time.time() >= self.token_exp:
            await self.close(code=4401)
            return

        # 3. Handle binary PCM audio chunks
        if bytes_data is not None:
            chunk_len = len(bytes_data)

            if chunk_len == 0:
                return

            if chunk_len > MAX_AUDIO_CHUNK_SIZE_BYTES:
                await self.send(
                    text_data=json.dumps({
                        "type": "error",
                        "message": f"Audio chunk exceeds maximum allowed size ({MAX_AUDIO_CHUNK_SIZE_BYTES} bytes).",
                    })
                )
                return

            if chunk_len % 2 != 0:
                await self.send(
                    text_data=json.dumps({
                        "type": "error",
                        "message": "Invalid PCM chunk: odd byte length for 16-bit audio.",
                    })
                )
                return

            if self.recognizer is None:
                return

            # Feed PCM bytes to the Kaldi recognizer
            try:
                is_endpoint = self.recognizer.AcceptWaveform(bytes_data)
                if is_endpoint:
                    raw_result = self.recognizer.Result()
                    await self._handle_finalized_transcript(
                        raw_result,
                        log_prefix="[NoTox Moderation]",
                    )
                else:
                    try:
                        partial_fn = getattr(self.recognizer, "PartialResult", None)
                        if callable(partial_fn):
                            partial_raw = partial_fn()
                            if isinstance(partial_raw, str) and partial_raw:
                                p_data = json.loads(partial_raw)
                                p_text = str(p_data.get("partial", "")).strip()
                                if p_text and StreamModerationService.contains_profanity(p_text):
                                    p_mod = await moderate_transcript_sync(p_text, None)
                                    if p_mod and p_mod.is_flagged:
                                        await self.send(
                                            text_data=json.dumps({
                                                "type": "transcript",
                                                "is_final": False,
                                                "text": p_text,
                                                "words": [],
                                                "moderation": p_mod.to_dict(),
                                                "censor": True,
                                            })
                                        )
                    except Exception:
                        pass
            except Exception as exc:
                print(f"[NoTox] Recognition processing error: {exc}")
            return

        # 4. Handle text control messages (e.g. finalize/flush)
        if text_data is not None:
            try:
                cmd = json.loads(text_data)
            except (json.JSONDecodeError, TypeError):
                await self.send(
                    text_data=json.dumps({
                        "type": "error",
                        "message": "Invalid control message payload.",
                    })
                )
                return

            if not isinstance(cmd, dict):
                return

            msg_type = cmd.get("type")
            if msg_type in ("finalize", "flush"):
                if self.recognizer is not None:
                    raw_final = self.recognizer.FinalResult()
                    await self._handle_finalized_transcript(
                        raw_final,
                        log_prefix="[NoTox Moderation - Final]",
                    )
            else:
                await self.send(
                    text_data=json.dumps({
                        "type": "error",
                        "message": f"Unrecognized control message type: {msg_type}",
                    })
                )
