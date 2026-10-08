import json
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.chat.authentication import check_user_restriction, get_user_from_token
from apps.chat.services import ChatService


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

        # Check message for profanity before saving or broadcasting.
        is_toxic = ChatService.contains_profanity(message)

        if is_toxic:
            await self.send(text_data=json.dumps({
                "type": "moderation_block",
                "message": message,
                "blocked": True,
            }))
            return

        # Persist message to database before broadcasting.
        chat_msg = await self.persist_message(self.user, message)

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

    @database_sync_to_async
    def persist_message(self, user, content: str):
        return ChatService.save_message(sender=user, content=content)

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "message",
            "id": event["id"],
            "message": event["message"],
            "username": event["username"],
            "display_name": event["display_name"],
            "created_at": event["created_at"],
        }))