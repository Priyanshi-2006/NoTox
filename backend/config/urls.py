from django.contrib import admin
from django.urls import include, path
from apps.accounts.views import ProfileView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/profile/", ProfileView.as_view(), name="profile"),
]

