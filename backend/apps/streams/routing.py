from django.urls import path
from .consumers import StreamConsumer

websocket_urlpatterns = [
    path("ws/streams/<uuid:stream_id>/", StreamConsumer.as_asgi()),
]