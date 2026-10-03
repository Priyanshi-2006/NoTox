
from django.urls import path

from apps.chat.consumers import GlobalChatConsumer

websocket_urlpatterns = [
    path("ws/chat/", GlobalChatConsumer.as_asgi()),
]