from datetime import datetime
from typing import List, Optional

from apps.chat.models import ChatMessage


class ChatService:
    @classmethod
    def save_message(cls, sender, content: str) -> ChatMessage:
        return ChatMessage.objects.create(
            sender=sender,
            content=content,
        )

    @classmethod
    def get_messages(cls, limit: int = 50, before: Optional[datetime] = None) -> List[ChatMessage]:
        """
        Returns the latest `limit` messages oldest-first, optionally before a cursor datetime.
        """
        queryset = ChatMessage.objects.select_related("sender").all()
        if before is not None:
            queryset = queryset.filter(created_at__lt=before)

        # Query the latest `limit` messages matching the filter
        latest_messages = list(queryset.order_by("-created_at")[:limit])
        # Order oldest-first
        latest_messages.reverse()
        return latest_messages
