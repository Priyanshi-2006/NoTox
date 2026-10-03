"""
ASGI entrypoint for NoTox.

Stage 1 exposes a plain Django ASGI application. When real-time chat is
built, this file will grow a ProtocolTypeRouter that dispatches "http" to
this same Django app and "websocket" to Channels consumers — nothing
here needs to change shape to support that, only extend it.
Routes HTTP requests to Django and WebSocket
connections to Django Channels consumers.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

# Initialize Django first.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from apps.chat.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(websocket_urlpatterns),
})