from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Stream


class StreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.group = None
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.stream_id = str(self.scope["url_route"]["kwargs"]["stream_id"])
        stream = await self.get_stream()
        if stream is None or stream.status != Stream.Status.LIVE:
            await self.close(code=4404)
            return

        self.is_host = stream.host_id == user.id
        self.group = f"stream_{self.stream_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "role", "role": "host" if self.is_host else "viewer"})

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            self.group,
            {"type": "relay", "payload": content, "sender": self.channel_name},
        )

    async def relay(self, event):
        if event["sender"] != self.channel_name:
            await self.send_json(event["payload"])

    @database_sync_to_async
    def get_stream(self):
        return Stream.objects.filter(pk=self.stream_id).first()