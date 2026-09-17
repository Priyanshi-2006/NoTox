import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserRole(models.TextChoices):
    REGULAR = "regular", "Regular"
    ADMIN = "admin", "Admin"


class UserManager(BaseUserManager):
    """
    Custom manager for the UUID-keyed User model. Django's default
    UserManager assumes an auto-increment PK and a `username` that is
    always required in the same way — this keeps creation explicit
    instead.
    """

    use_in_migrations = True

    def _create_user(self, username, email, password, **extra_fields):
        if not username:
            raise ValueError("Users must have a username.")
        if not email:
            raise ValueError("Users must have an email address.")

        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.REGULAR)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Stage 1 user model.

    Only the fields Stage 1 needs to exist are populated with real
    behaviour (trust_score, strike_count, is_restricted, restricted_until
    are storage-only placeholders — the engines that compute/enforce
    them are built in later stages and must not require a model change
    to plug in).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True, default="")

    role = models.CharField(
        max_length=10, choices=UserRole.choices, default=UserRole.REGULAR
    )

    is_phone_verified = models.BooleanField(default=False)

    # Placeholders for later-stage trust/moderation engines. Stage 1 only
    # establishes the fields and their defaults; nothing here computes
    # or mutates them yet.
    trust_score = models.IntegerField(default=100)
    strike_count = models.PositiveIntegerField(default=0)
    is_restricted = models.BooleanField(default=False)
    restricted_until = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]

    def __str__(self):
        return self.username

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN
