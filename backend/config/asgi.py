"""
ASGI entrypoint for NoTox.

Routes HTTP requests to Django and WebSocket
connections to Django Channels consumers.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

# Initialize Django first.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from apps.chat.routing import websocket_urlpatterns as chat_ws_urlpatterns
from apps.streams.routing import websocket_urlpatterns as stream_ws_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(chat_ws_urlpatterns + stream_ws_urlpatterns),
})