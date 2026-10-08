from datetime import datetime
from typing import List, Optional

from better_profanity import profanity

from apps.chat.models import ChatMessage


# Load the default profanity word list
profanity.load_censor_words()


class ChatService:

    @classmethod
    def contains_profanity(cls, content: str) -> bool:
        """
        Check whether the message contains profanity.

        Returns:
            True  -> profanity detected
            False -> no profanity detected
        """
        return profanity.contains_profanity(content)

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
