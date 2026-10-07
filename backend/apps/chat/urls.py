from django.urls import path

from apps.chat.views import ChatMessageListView

urlpatterns = [
    path("messages/", ChatMessageListView.as_view(), name="chat-messages"),
]
