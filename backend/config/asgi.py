"""
ASGI entrypoint for NoTox.

Stage 1 exposes a plain Django ASGI application. When real-time chat is
built, this file will grow a ProtocolTypeRouter that dispatches "http" to
this same Django app and "websocket" to Channels consumers — nothing
here needs to change shape to support that, only extend it.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
