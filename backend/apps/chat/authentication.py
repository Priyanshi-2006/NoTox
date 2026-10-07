from channels.db import database_sync_to_async
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User


@database_sync_to_async
def get_user_from_token(token: str):
    """
    Validates the JWT access token, retrieves the active user, and checks restriction status.
    Runs inside database_sync_to_async to permit lazy DB updates in is_currently_restricted.
    Returns (user, exp, is_restricted) tuple if valid, or (None, None, False) on failure.
    """
    try:
        access_token = AccessToken(token)
        user_id = access_token["user_id"]
        exp = access_token.get("exp")

        user = User.objects.get(
            id=user_id,
            is_active=True,
        )

        is_restricted = user.is_currently_restricted()
        return user, exp, is_restricted

    except (InvalidToken, TokenError, User.DoesNotExist, KeyError, ValueError, TypeError):
        return None, None, False


@database_sync_to_async
def check_user_restriction(user_id):
    """
    Re-checks the user from the database to ensure the user exists, is active,
    and is not restricted. Handles lazy clearance of expired restrictions.
    Returns (is_restricted: bool, user: User | None).
    """
    try:
        user = User.objects.get(id=user_id, is_active=True)
        return user.is_currently_restricted(), user
    except User.DoesNotExist:
        return True, None