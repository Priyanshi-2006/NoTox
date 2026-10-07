import json
import time
from datetime import timedelta
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User, UserRole
from apps.chat.consumers import GlobalChatConsumer
from apps.chat.models import ChatMessage
from config.asgi import application


def sync_get_access_token(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


@database_sync_to_async
def get_access_token(user):
    return sync_get_access_token(user)


@database_sync_to_async
def update_user_fields(user, **kwargs):
    for field, value in kwargs.items():
        setattr(user, field, value)
    user.save(update_fields=list(kwargs.keys()))


class WebSocketAuthenticationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
            display_name="Alice Wonderland",
        )

    async def test_authenticate_success(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # First message from server is auth_required
        auth_req = await communicator.receive_json_from()
        self.assertEqual(auth_req["type"], "auth_required")

        token = await get_access_token(self.user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })

        auth_resp = await communicator.receive_json_from()
        self.assertEqual(auth_resp["type"], "authenticated")
        self.assertEqual(auth_resp["username"], "alice")
        self.assertEqual(auth_resp["display_name"], "Alice Wonderland")

        await communicator.disconnect()

    async def test_invalid_token_closes_4401(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        await communicator.send_json_to({
            "type": "authenticate",
            "token": "invalid.jwt.token",
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4401)

    async def test_no_authenticate_message_closes_4401(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        await communicator.send_json_to({
            "type": "message",
            "message": "Hello without auth",
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4401)

    async def test_expired_token_closes_4401_on_message(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        await communicator.receive_json_from()  # authenticated

        # Fast forward time past token expiry
        with patch("apps.chat.consumers.time.time", return_value=time.time() + 86400 * 30):
            await communicator.send_json_to({
                "type": "message",
                "message": "Message after token expired",
            })

            close_event = await communicator.receive_output()
            self.assertEqual(close_event["type"], "websocket.close")
            self.assertEqual(close_event["code"], 4401)


class WebSocketRestrictionTests(TransactionTestCase):
    def setUp(self):
        self.restricted_user = User.objects.create_user(
            username="bob_restricted",
            email="bob@example.com",
            password="StrongPass123!",
            is_restricted=True,
        )
        self.active_user = User.objects.create_user(
            username="charlie",
            email="charlie@example.com",
            password="StrongPass123!",
        )

    async def test_restricted_user_closes_4403_on_connect(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.restricted_user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4403)

    async def test_user_restricted_mid_session_closes_4403_on_next_message(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.active_user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        await communicator.receive_json_from()  # authenticated

        # Restrict user mid-session in DB
        await update_user_fields(self.active_user, is_restricted=True)

        await communicator.send_json_to({
            "type": "message",
            "message": "Attempting to send while restricted",
        })

        close_event = await communicator.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        self.assertEqual(close_event["code"], 4403)

    async def test_expired_restricted_until_treated_as_unrestricted(self):
        past_time = timezone.now() - timedelta(minutes=10)
        await update_user_fields(self.restricted_user, restricted_until=past_time)

        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.restricted_user)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })

        auth_resp = await communicator.receive_json_from()
        self.assertEqual(auth_resp["type"], "authenticated")
        self.assertEqual(auth_resp["username"], "bob_restricted")

        await communicator.disconnect()


class WebSocketMessageTests(TransactionTestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="StrongPass123!",
            display_name="User One",
        )
        self.user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="StrongPass123!",
            display_name="User Two",
        )

    async def test_invalid_messages_ignored_and_not_stored(self):
        communicator = WebsocketCommunicator(application, "/ws/chat/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.receive_json_from()  # auth_required

        token = await get_access_token(self.user1)
        await communicator.send_json_to({
            "type": "authenticate",
            "token": token,
        })
        await communicator.receive_json_from()  # authenticated

        # Empty whitespace string
        await communicator.send_json_to({"type": "message", "message": "   "})
        # Non-string message
        await communicator.send_json_to({"type": "message", "message": 12345})
        await communicator.send_json_to({"type": "message", "message": ["not", "string"]})
        # 2001 characters
        await communicator.send_json_to({"type": "message", "message": "x" * 2001})

        # Check no message received
        self.assertTrue(await communicator.receive_nothing(timeout=0.2))

        # Check nothing persisted
        count = await ChatMessage.objects.acount()
        self.assertEqual(count, 0)

        await communicator.disconnect()

    async def test_valid_message_stored_and_broadcast_to_multiple_clients(self):
        comm1 = WebsocketCommunicator(application, "/ws/chat/")
        comm2 = WebsocketCommunicator(application, "/ws/chat/")

        connected1, _ = await comm1.connect()
        connected2, _ = await comm2.connect()
        self.assertTrue(connected1)
        self.assertTrue(connected2)

        await comm1.receive_json_from()
        await comm2.receive_json_from()

        token1 = await get_access_token(self.user1)
        token2 = await get_access_token(self.user2)

        await comm1.send_json_to({"type": "authenticate", "token": token1})
        await comm2.send_json_to({"type": "authenticate", "token": token2})

        await comm1.receive_json_from()
        await comm2.receive_json_from()

        # user1 sends message
        await comm1.send_json_to({
            "type": "message",
            "message": "Hello from user1!",
        })

        msg1 = await comm1.receive_json_from()
        msg2 = await comm2.receive_json_from()

        for msg in (msg1, msg2):
            self.assertEqual(msg["type"], "message")
            self.assertEqual(msg["message"], "Hello from user1!")
            self.assertEqual(msg["username"], "user1")
            self.assertEqual(msg["display_name"], "User One")
            self.assertIn("id", msg)
            self.assertIn("created_at", msg)

        # Verify persisted in database
        saved_msg = await ChatMessage.objects.select_related("sender").afirst()
        self.assertIsNotNone(saved_msg)
        self.assertEqual(saved_msg.content, "Hello from user1!")
        self.assertEqual(saved_msg.sender, self.user1)
        self.assertEqual(str(saved_msg.id), msg1["id"])

        await comm1.disconnect()
        await comm2.disconnect()


class ChatHistoryApiTests(APITestCase):
    def setUp(self):
        self.url = reverse("chat-messages")
        self.user = User.objects.create_user(
            username="history_user",
            email="history@example.com",
            password="StrongPass123!",
            display_name="History User",
        )
        self.restricted_user = User.objects.create_user(
            username="restricted_user",
            email="restr@example.com",
            password="StrongPass123!",
            is_restricted=True,
        )

    def _login(self, user):
        token = sync_get_access_token(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_history_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_history_blocks_restricted_user(self):
        self._login(self.restricted_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_history_returns_last_50_oldest_first(self):
        self._login(self.user)

        # Create 60 messages with increasing created_at
        base_time = timezone.now() - timedelta(hours=2)
        created_messages = []
        for i in range(60):
            msg = ChatMessage.objects.create(
                sender=self.user,
                content=f"Message {i + 1}",
            )
            # Update created_at so ordering is explicit
            ChatMessage.objects.filter(id=msg.id).update(
                created_at=base_time + timedelta(minutes=i)
            )
            msg.refresh_from_db()
            created_messages.append(msg)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 50)

        # The last 50 are messages 11 through 60 (index 10 to 59)
        expected_contents = [f"Message {i + 1}" for i in range(10, 60)]
        actual_contents = [item["content"] for item in response.data]
        self.assertEqual(actual_contents, expected_contents)

        # Verify structure
        first_item = response.data[0]
        self.assertEqual(first_item["username"], "history_user")
        self.assertEqual(first_item["display_name"], "History User")
        self.assertIn("id", first_item)
        self.assertIn("created_at", first_item)
        self.assertIn("message", first_item)

    def test_history_before_pagination(self):
        self._login(self.user)

        base_time = timezone.now() - timedelta(hours=2)
        messages = []
        for i in range(20):
            msg = ChatMessage.objects.create(
                sender=self.user,
                content=f"Pagination Message {i + 1}",
            )
            ChatMessage.objects.filter(id=msg.id).update(
                created_at=base_time + timedelta(minutes=i)
            )
            msg.refresh_from_db()
            messages.append(msg)

        # Use the 10th message (index 9) as the before cursor
        cursor = messages[9].created_at.isoformat()
        response = self.client.get(self.url, {"before": cursor})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Expected: messages 1 to 9 (oldest first)
        expected_contents = [f"Pagination Message {i + 1}" for i in range(9)]
        actual_contents = [item["content"] for item in response.data]
        self.assertEqual(actual_contents, expected_contents)

    def test_history_allowed_when_restricted_until_expired(self):
        self.restricted_user.restricted_until = timezone.now() - timedelta(minutes=5)
        self.restricted_user.save(update_fields=["restricted_until"])

        self._login(self.restricted_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
