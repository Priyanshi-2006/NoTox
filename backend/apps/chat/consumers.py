
import json

from channels.generic.websocket import AsyncWebsocketConsumer


class GlobalChatConsumer(AsyncWebsocketConsumer):
    GROUP_NAME = "global_chat"

    async def connect(self):
        await self.channel_layer.group_add(
            self.GROUP_NAME,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.GROUP_NAME,
            self.channel_name,
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        message = data.get("message", "")

        if not isinstance(message, str) or not message.strip():
            return

        await self.channel_layer.group_send(
            self.GROUP_NAME,
            {
                "type": "chat_message",
                "message": message.strip(),
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "message": event["message"],
        }))