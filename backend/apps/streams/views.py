from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Stream
from .serializers import StreamSerializer


class StreamListCreateView(generics.ListCreateAPIView):
    serializer_class = StreamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Stream.objects.filter(status=Stream.Status.LIVE).select_related("host")

    def perform_create(self, serializer):
        serializer.save(host=self.request.user)


class StreamEndView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        stream = get_object_or_404(Stream, pk=pk)
        if stream.host != request.user:
            return Response({"detail": "Only the host can end this stream."},
                            status=status.HTTP_403_FORBIDDEN)
        if stream.status == Stream.Status.LIVE:
            stream.status = Stream.Status.ENDED
            stream.ended_at = timezone.now()
            stream.save()
        return Response(StreamSerializer(stream).data)