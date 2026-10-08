from rest_framework import serializers
from .models import Stream


class StreamSerializer(serializers.ModelSerializer):
    host_username = serializers.CharField(source="host.username", read_only=True)

    class Meta:
        model = Stream
        fields = ["id", "title", "status", "host_username", "started_at", "ended_at"]
        read_only_fields = ["id", "status", "host_username", "started_at", "ended_at"]