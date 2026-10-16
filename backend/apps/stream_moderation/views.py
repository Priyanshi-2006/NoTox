from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsNotRestricted
from apps.stream_moderation.services import StreamModerationService


class ModerateTranscriptView(APIView):
    """
    POST /api/stream-moderation/moderate/

    Accepts text transcripts and optional word timestamps from a speech-to-text
    component and evaluates them against the existing chat moderation engine.
    """
    permission_classes = [permissions.IsAuthenticated, IsNotRestricted]

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response(
                {"detail": "Request payload must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        text = request.data.get("text")
        if text is None:
            return Response(
                {"detail": "Field 'text' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(text, str):
            return Response(
                {"detail": "Field 'text' must be a string."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        words = request.data.get("words")
        if words is not None and not isinstance(words, list):
            return Response(
                {"detail": "Field 'words' must be a list if provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = StreamModerationService.moderate_transcript(text=text, words=words)
        return Response(result.to_dict(), status=status.HTTP_200_OK)
