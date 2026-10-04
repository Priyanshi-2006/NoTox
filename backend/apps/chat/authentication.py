
from channels.db import database_sync_to_async
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User


@database_sync_to_async
def get_user_from_token(token):
    try:
        access_token = AccessToken(token)
        user_id = access_token["user_id"]

        user = User.objects.get(
            id=user_id,
            is_active=True,
        )

        return user

    except (InvalidToken, TokenError, User.DoesNotExist, KeyError, ValueError):
        return None