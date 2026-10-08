from django.urls import path
from .consumers import StreamConsumer
from .middleware import JWTAuthMiddleware

websocket_urlpatterns = [
    path("ws/streams/<uuid:stream_id>/", JWTAuthMiddleware(StreamConsumer.as_asgi())),
]