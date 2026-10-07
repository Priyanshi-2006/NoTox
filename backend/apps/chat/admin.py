from django.contrib import admin

from apps.chat.models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "sender", "content", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "sender__username")
