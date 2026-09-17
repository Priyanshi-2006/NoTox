import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Wraps DRF's default handler so every error response has a consistent
    shape ({"detail": ...} or {"errors": {...}}) and unhandled exceptions
    never leak a Django debug page or raw traceback to the frontend.
    """
    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict) and "detail" not in response.data:
            response.data = {"errors": response.data}
        return response

    # Anything DRF didn't already turn into a Response (e.g. an
    # unexpected server-side exception) is logged and returned as a
    # generic 500 — never the raw exception text.
    logger.exception("Unhandled exception in API view", exc_info=exc)
    return Response(
        {"detail": "An unexpected error occurred. Please try again later."},
        status=500,
    )
