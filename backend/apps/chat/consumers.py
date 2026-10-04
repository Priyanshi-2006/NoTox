
import json

from channels.generic.websocket import AsyncWebsocketConsumer

from apps.chat.authentication import get_user_from_token


class GlobalChatConsumer(AsyncWebsocketConsumer):
    GROUP_NAME = "global_chat"

    async def connect(self):
        self.user = None
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

            user = await get_user_from_token(token.strip())

            if user is None or user.is_restricted:
                await self.close(code=4403)
                return

            self.user = user
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

        # Ignore any message that is not a chat message.
        if data.get("type", "message") != "message":
            return

        message = data.get("message", "")

        if not isinstance(message, str) or not message.strip():
            return

        message = message.strip()

        if len(message) > 2000:
            return

        await self.channel_layer.group_send(
            self.GROUP_NAME,
            {
                "type": "chat_message",
                "message": message,
                "username": self.user.username,
                "display_name": self.user.display_title,
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "message",
            "message": event["message"],
            "username": event["username"],
            "display_name": event["display_name"],
        }))