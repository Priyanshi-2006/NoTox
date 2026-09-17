from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import User

phone_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Enter a valid phone number in international format, e.g. +911234567890.",
)


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of a user, used by /me/ and nested elsewhere."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "phone_number",
            "role",
            "is_phone_verified",
            "trust_score",
            "strike_count",
            "is_restricted",
            "restricted_until",
            "created_at",
        ]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    phone_number = serializers.CharField(
        required=False, allow_blank=True, validators=[phone_validator]
    )

    class Meta:
        model = User
        fields = ["username", "email", "password", "phone_number"]

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    """
    Accepts either a username or an email in `identifier`, plus password.
    Resolution to a concrete username happens here so the view stays thin.
    """

    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get("identifier")
        password = attrs.get("password")

        username = identifier
        if "@" in identifier:
            try:
                username = User.objects.get(email__iexact=identifier).username
            except User.DoesNotExist:
                username = identifier  # let authenticate() fail uniformly below

        user = authenticate(
            request=self.context.get("request"), username=username, password=password
        )

        if user is None:
            raise serializers.ValidationError(
                "Invalid credentials.", code="authorization"
            )
        if not user.is_active:
            raise serializers.ValidationError(
                "This account is inactive.", code="authorization"
            )

        attrs["user"] = user
        return attrs
