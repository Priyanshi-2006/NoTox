from django.urls import path
from .views import StreamListCreateView, StreamEndView

urlpatterns = [
    path("", StreamListCreateView.as_view()),
    path("<uuid:pk>/end/", StreamEndView.as_view()),
]