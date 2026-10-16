from django.urls import path

from apps.stream_moderation.views import ModerateTranscriptView

urlpatterns = [
    path("moderate/", ModerateTranscriptView.as_view(), name="stream-moderation-moderate"),
]
