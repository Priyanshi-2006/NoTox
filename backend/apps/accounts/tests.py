from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User


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

    def test_default_role_regular(self):
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.data["user"]["role"], "regular")

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


class MeEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="priyanshi",
            email="priyanshi@example.com",
            password="StrongPass123!",
        )
        self.url = reverse("auth-me")

    def _login(self):
        login_url = reverse("auth-login")
        response = self.client.post(
            login_url, {"identifier": "priyanshi", "password": "StrongPass123!"}
        )
        return response.data["tokens"]["access"]

    def test_me_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_current_user(self):
        access = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "priyanshi")

    def test_me_reflects_admin_role(self):
        admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="StrongPass123!"
        )
        login_url = reverse("auth-login")
        response = self.client.post(
            login_url, {"identifier": "admin", "password": "StrongPass123!"}
        )
        access = response.data["tokens"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get(self.url)
        self.assertEqual(response.data["role"], "admin")
