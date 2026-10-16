from django.urls import path

from apps.transcription.consumers import TranscriptionConsumer

websocket_urlpatterns = [
    path("ws/transcription/", TranscriptionConsumer.as_asgi()),
]
