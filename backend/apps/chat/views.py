from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsNotRestricted
from apps.chat.serializers import ChatMessageSerializer
from apps.chat.services import ChatService


class ChatMessageListView(APIView):
    permission_classes = [IsAuthenticated, IsNotRestricted]

    def get(self, request):
        before_param = request.query_params.get("before")
        before_dt = None
        if before_param:
            if " " in before_param and "+" not in before_param:
                before_param = before_param.replace(" ", "+")
            before_dt = parse_datetime(before_param)
            if before_dt is None:
                return Response(
                    {"detail": "Invalid 'before' datetime format. Expected ISO-8601 format."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        messages = ChatService.get_messages(limit=50, before=before_dt)
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
