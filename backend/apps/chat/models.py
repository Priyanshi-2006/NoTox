import uuid

from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_messages",
    )
    content = models.TextField(max_length=2000) 
    blocked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "chat_message"
        ordering = ["created_at"]

    def __str__(self):
        username = self.sender.username if self.sender else "Deleted User"
        return f"{username}: {self.content[:30]}"


class ModerationLog(models.Model):
    """
    Moderation audit log storing outcomes across pipeline layers.
    Fast-path 'clean' rows store metadata only (empty text) for privacy and volume.
    Blocked or flagged items store the offending text for auditing and appeals.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    stage = models.CharField(max_length=20, db_index=True)
    verdict = models.CharField(max_length=20, db_index=True)
    bloom_status = models.CharField(max_length=20)
    latency_ms = models.FloatField()
    text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "moderation_log"
        ordering = ["-created_at"]

    def __str__(self):
        username = self.user.username if self.user else "Anonymous"
        return f"[{self.stage}/{self.verdict}] {username} ({self.latency_ms:.2f}ms)"
