from rest_framework import serializers

from apps.chat.models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    message = serializers.CharField(source="content", read_only=True)
    username = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "sender",
            "content",
            "message",
            "username",
            "display_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_username(self, obj):
        return obj.sender.username if obj.sender else "Deleted User"

    def get_display_name(self, obj):
        if obj.sender:
            return obj.sender.display_title
        return "Deleted User"
