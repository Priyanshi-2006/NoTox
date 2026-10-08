import uuid
from django.conf import settings
from django.db import models


class Stream(models.Model):
    class Status(models.TextChoices):
        LIVE = "live", "Live"
        ENDED = "ended", "Ended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="streams"
    )
    title = models.CharField(max_length=120)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"