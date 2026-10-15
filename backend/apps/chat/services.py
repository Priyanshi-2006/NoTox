from datetime import datetime
from typing import List, Optional

from better_profanity import profanity

from apps.chat.models import ChatMessage, ModerationLog


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
    def save_message(cls, sender, content: str, blocked: bool = False) -> ChatMessage:
        return ChatMessage.objects.create(
            sender=sender,
            content=content,
            blocked=blocked,
        )

    @classmethod
    def log_moderation(
        cls,
        user,
        message: Optional[ChatMessage],
        stage: str,
        verdict: str,
        bloom_status: str,
        latency_ms: float,
        raw_text: str = "",
    ) -> ModerationLog:
        """
        Store moderation outcome. Fast-path 'clean' rows store metadata only
        (empty text) for privacy and volume. Offending text is stored only for
        flagged or blocked items.
        """
        text_to_store = raw_text if verdict in ("blocked", "flagged") else ""
        return ModerationLog.objects.create(
            user=user,
            message=message,
            stage=stage,
            verdict=verdict,
            bloom_status=bloom_status,
            latency_ms=latency_ms,
            text=text_to_store,
        )

    @classmethod
    def get_messages(cls, limit: int = 50, before: Optional[datetime] = None) -> List[ChatMessage]:
        """
        Returns the latest `limit` messages oldest-first, optionally before a cursor datetime.
        Excludes blocked messages.
        """
        queryset = ChatMessage.objects.select_related("sender").filter(blocked=False)
        if before is not None:
            queryset = queryset.filter(created_at__lt=before)

        # Query the latest `limit` messages matching the filter
        latest_messages = list(queryset.order_by("-created_at")[:limit])
        # Order oldest-first
        latest_messages.reverse()
        return latest_messages

