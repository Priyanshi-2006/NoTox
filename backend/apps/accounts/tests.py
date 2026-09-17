from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User, UserRole
from .permissions import IsAdminRole, IsModeratorRole
from .services import (
    INITIAL_TRUST_SCORE,
    MAX_TRUST_SCORE,
    MIN_TRUST_SCORE,
    TrustScoreService,
    decrease_trust_score,
    increase_trust_score,
    reset_trust_score,
    set_trust_score,
)


class RegistrationTests(APITestCase):
    def setUp(self):
        self.url = reverse("auth-register")
        self.payload = {
            "username": "priyanshi",
            "email": "priyanshi@example.com",
            "password": "StrongPass123!",
            "phone_number": "+911234567890",
        }

    def test_register_success(self):
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])
        self.assertEqual(response.data["user"]["username"], "priyanshi")

    def test_default_role(self):
        response = self.client.post(self.url, self.payload)
        self.assertIn(response.data["user"]["role"], [UserRole.USER, UserRole.REGULAR])

    def test_default_trust_score(self):
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.data["user"]["trust_score"], 100)

    def test_default_strike_count(self):
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.data["user"]["strike_count"], 0)

    def test_duplicate_username_rejected(self):
        self.client.post(self.url, self.payload)
        duplicate = {**self.payload, "email": "other@example.com"}
        response = self.client.post(self.url, duplicate)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_rejected(self):
        self.client.post(self.url, self.payload)
        duplicate = {**self.payload, "username": "someoneelse"}
        response = self.client.post(self.url, duplicate)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="priyanshi",
            email="priyanshi@example.com",
            password="StrongPass123!",
        )
        self.url = reverse("auth-login")

    def test_login_success_with_username(self):
        response = self.client.post(
            self.url, {"identifier": "priyanshi", "password": "StrongPass123!"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["tokens"])

    def test_login_success_with_email(self):
        response = self.client.post(
            self.url,
            {"identifier": "priyanshi@example.com", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_invalid_password(self):
        response = self.client.post(
            self.url, {"identifier": "priyanshi", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProfileEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="priyanshi",
            email="priyanshi@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="StrongPass123!",
        )
        self.me_url = reverse("auth-me")
        self.profile_url = reverse("profile")

    def _login(self, username="priyanshi", password="StrongPass123!"):
        login_url = reverse("auth-login")
        response = self.client.post(
            login_url, {"identifier": username, "password": password}
        )
        return response.data["tokens"]["access"]

    def test_profile_requires_authentication(self):
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        me_response = self.client.get(self.me_url)
        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_retrieval_authenticated(self):
        access = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "priyanshi")
        self.assertEqual(response.data["email"], "priyanshi@example.com")
        self.assertEqual(response.data["trust_score"], 100)
        self.assertEqual(response.data["display_name"], "")
        self.assertEqual(response.data["bio"], "")
        self.assertEqual(response.data["avatar"], "")

    def test_profile_update_allowed_fields(self):
        access = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        update_payload = {
            "display_name": "Priyanshi S.",
            "bio": "Building NoTox moderation system.",
            "avatar": "https://example.com/avatar.png",
        }
        response = self.client.patch(self.profile_url, update_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_name"], "Priyanshi S.")
        self.assertEqual(response.data["bio"], "Building NoTox moderation system.")
        self.assertEqual(response.data["avatar"], "https://example.com/avatar.png")

        # Confirm persisted in DB
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "Priyanshi S.")
        self.assertEqual(self.user.bio, "Building NoTox moderation system.")
        self.assertEqual(self.user.avatar, "https://example.com/avatar.png")

    def test_user_cannot_modify_trust_score_via_api(self):
        access = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.patch(
            self.profile_url,
            {"trust_score": 50, "display_name": "Test User"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["trust_score"], 100)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 100)

    def test_user_cannot_modify_role_via_api(self):
        access = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.patch(
            self.profile_url,
            {"role": "admin", "display_name": "Wannabe Admin"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], UserRole.USER)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, UserRole.USER)

    def test_different_users_cannot_modify_each_others_profile(self):
        # User A updates profile
        access_a = self._login("priyanshi", "StrongPass123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_a}")
        self.client.patch(
            self.profile_url,
            {"display_name": "User A Name"},
        )

        # User B logs in and fetches profile -> gets User B's own data, not User A's
        access_b = self._login("otheruser", "StrongPass123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_b}")
        response_b = self.client.get(self.profile_url)
        self.assertEqual(response_b.data["username"], "otheruser")
        self.assertEqual(response_b.data["display_name"], "")

        # User B updating only affects User B
        self.client.patch(self.profile_url, {"display_name": "User B Name"})
        self.user.refresh_from_db()
        self.other_user.refresh_from_db()
        self.assertEqual(self.user.display_name, "User A Name")
        self.assertEqual(self.other_user.display_name, "User B Name")


class TrustScoreServiceTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="priyanshi",
            email="priyanshi@example.com",
            password="StrongPass123!",
        )

    def test_initial_trust_score_is_100(self):
        self.assertEqual(self.user.trust_score, INITIAL_TRUST_SCORE)
        self.assertEqual(INITIAL_TRUST_SCORE, 100)

    def test_clamp_score(self):
        self.assertEqual(TrustScoreService.clamp_score(150), 100)
        self.assertEqual(TrustScoreService.clamp_score(-50), 0)
        self.assertEqual(TrustScoreService.clamp_score(75), 75)

    def test_increase_trust_score_capped_at_100(self):
        self.user.trust_score = 90
        self.user.save()
        new_score = increase_trust_score(self.user, 20)
        self.assertEqual(new_score, MAX_TRUST_SCORE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 100)

    def test_decrease_trust_score_floored_at_0(self):
        self.user.trust_score = 15
        self.user.save()
        new_score = decrease_trust_score(self.user, 30)
        self.assertEqual(new_score, MIN_TRUST_SCORE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 0)

    def test_set_trust_score_clamped(self):
        set_trust_score(self.user, 85)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 85)

        set_trust_score(self.user, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 100)

        set_trust_score(self.user, -10)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 0)

    def test_reset_trust_score(self):
        set_trust_score(self.user, 40)
        self.assertEqual(self.user.trust_score, 40)
        reset_trust_score(self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.trust_score, 100)

    def test_negative_delta_raises_value_error(self):
        with self.assertRaises(ValueError):
            increase_trust_score(self.user, -10)
        with self.assertRaises(ValueError):
            decrease_trust_score(self.user, -10)


class RoleAndPermissionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="regular_user",
            email="user@example.com",
            password="StrongPass123!",
            role=UserRole.USER,
        )
        self.moderator = User.objects.create_user(
            username="mod_user",
            email="mod@example.com",
            password="StrongPass123!",
            role=UserRole.MODERATOR,
        )
        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin@example.com",
            password="StrongPass123!",
        )

    def test_role_properties(self):
        self.assertFalse(self.user.is_moderator)
        self.assertFalse(self.user.is_admin)

        self.assertTrue(self.moderator.is_moderator)
        self.assertFalse(self.moderator.is_admin)

        self.assertTrue(self.admin.is_moderator)
        self.assertTrue(self.admin.is_admin)

    def test_permission_classes(self):
        class DummyRequest:
            def __init__(self, u):
                self.user = u

        admin_perm = IsAdminRole()
        mod_perm = IsModeratorRole()

        # Regular user
        self.assertFalse(admin_perm.has_permission(DummyRequest(self.user), None))
        self.assertFalse(mod_perm.has_permission(DummyRequest(self.user), None))

        # Moderator
        self.assertFalse(admin_perm.has_permission(DummyRequest(self.moderator), None))
        self.assertTrue(mod_perm.has_permission(DummyRequest(self.moderator), None))

        # Admin
        self.assertTrue(admin_perm.has_permission(DummyRequest(self.admin), None))
        self.assertTrue(mod_perm.has_permission(DummyRequest(self.admin), None))

