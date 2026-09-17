from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["-created_at"]
    list_display = [
        "username",
        "display_name",
        "email",
        "role",
        "is_phone_verified",
        "trust_score",
        "strike_count",
        "is_restricted",
        "is_active",
        "created_at",
    ]
    list_filter = ["role", "is_phone_verified", "is_restricted", "is_active"]
    search_fields = ["username", "display_name", "email", "phone_number"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("id", "username", "password")}),
        (
            "Personal & Profile info",
            {"fields": ("display_name", "bio", "avatar", "email", "phone_number")},
        ),

        (
            "Moderation state",
            {
                "fields": (
                    "trust_score",
                    "strike_count",
                    "is_restricted",
                    "restricted_until",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "role",
                    "is_phone_verified",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )
