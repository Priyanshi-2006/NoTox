from channels.generic.websocket import AsyncJsonWebsocketConsumer


class StreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.stream_id = str(self.scope["url_route"]["kwargs"]["stream_id"])
        self.group = f"stream_{self.stream_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content):
        await self.channel_layer.group_send(
            self.group,
            {"type": "relay", "payload": content, "sender": self.channel_name},
        )

    async def relay(self, event):
        if event["sender"] != self.channel_name:
            await self.send_json(event["payload"])