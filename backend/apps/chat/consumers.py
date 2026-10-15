import asyncio
import json
import logging
import time
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.chat.authentication import check_user_restriction, get_user_from_token
from apps.chat.moderation.pipeline import ModerationResult, get_moderation_pipeline
from apps.chat.services import ChatService

logger = logging.getLogger(__name__)


class GlobalChatConsumer(AsyncWebsocketConsumer):
    GROUP_NAME = "global_chat"

    async def connect(self):
        self.user = None
        self.token_exp = None
        self.is_authenticated = False

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "auth_required",
            "message": "Send your access token to authenticate.",
        }))

    async def disconnect(self, close_code):
        if self.is_authenticated:
            await self.channel_layer.group_discard(
                self.GROUP_NAME,
                self.channel_name,
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(data, dict):
            return

        # Authenticate before allowing chat messages.
        if not self.is_authenticated:
            if data.get("type") != "authenticate":
                await self.close(code=4401)
                return

            token = data.get("token")

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

            self.user = user
            self.token_exp = token_exp
            self.is_authenticated = True

            await self.channel_layer.group_add(
                self.GROUP_NAME,
                self.channel_name,
            )

            await self.send(text_data=json.dumps({
                "type": "authenticated",
                "username": user.username,
                "display_name": user.display_title,
            }))
            return

        # Check token expiry on incoming messages.
        if self.token_exp is not None and time.time() >= self.token_exp:
            await self.close(code=4401)
            return

        # Re-check user restriction status against database.
        is_restricted, current_user = await check_user_restriction(self.user.id)
        if is_restricted or current_user is None:
            await self.close(code=4403)
            return
        self.user = current_user

        # Ignore any message that is not a chat message.
        if data.get("type", "message") != "message":
            return

        raw_message = data.get("message")

        if not isinstance(raw_message, str):
            return

        message = raw_message.strip()

        if not message or len(message) > 2000:
            return

        # Run 3-stage moderation pipeline: Keyword -> Bloom -> Provider
        pipeline = get_moderation_pipeline()
        mod_result = await pipeline.evaluate(self.user, message)

        if mod_result.is_blocked:
            # Layer 1 instant block or Layer 3 block: same payload plus a generated id
            await self.log_moderation_event(self.user, None, mod_result, message)
            await self.send(text_data=json.dumps({
                "type": "moderation_block",
                "id": str(uuid.uuid4()),
                "message": message,
                "blocked": True,
            }))
            return

        # Persist allowed message to database before broadcasting.
        chat_msg = await self.persist_message(self.user, message)
        await self.log_moderation_event(self.user, chat_msg, mod_result, message)

        await self.channel_layer.group_send(
            self.GROUP_NAME,
            {
                "type": "chat_message",
                "id": str(chat_msg.id),
                "message": chat_msg.content,
                "username": self.user.username,
                "display_name": self.user.display_title,
                "created_at": chat_msg.created_at.isoformat(),
            },
        )

        # Audit sampling: asynchronously audit sample of clean messages
        if mod_result.audit_sampled:
            asyncio.create_task(self.run_audit_check(pipeline, self.user, chat_msg, message))

    async def run_audit_check(self, pipeline, user, chat_msg, text: str):
        """
        Asynchronously evaluate a fast-pathed clean message with the AI provider.
        Measures the real miss rate and logs any disagreements.
        """
        try:
            audit_result = await pipeline.provider.evaluate(user, text)
            if audit_result.verdict != "allowed":
                pipeline.metrics.audit_disagreements += 1
                logger.warning(
                    "Bloom audit disagreement detected! Message '%s' (id=%s) allowed by bloom, but provider verdict=%s (%s)",
                    text[:50],
                    chat_msg.id if chat_msg else "none",
                    audit_result.verdict,
                    audit_result.reason,
                )
                audit_mod = ModerationResult(
                    stage="audit",
                    verdict=audit_result.verdict,
                    bloom_status="clean",
                    latency_ms=audit_result.latency_ms,
                    reason=f"audit_disagreement: {audit_result.reason}",
                )
                await self.log_moderation_event(user, chat_msg, audit_mod, text)
        except Exception as exc:
            logger.debug("Asynchronous bloom audit error: %s", exc)

    @database_sync_to_async
    def persist_message(self, user, content: str):
        return ChatService.save_message(sender=user, content=content)

    @database_sync_to_async
    def log_moderation_event(self, user, message, result, raw_text: str):
        return ChatService.log_moderation(
            user=user,
            message=message,
            stage=result.stage,
            verdict=result.verdict,
            bloom_status=result.bloom_status,
            latency_ms=result.latency_ms,
            raw_text=raw_text,
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "message",
            "id": event["id"],
            "message": event["message"],
            "username": event["username"],
            "display_name": event["display_name"],
            "created_at": event["created_at"],
        }))