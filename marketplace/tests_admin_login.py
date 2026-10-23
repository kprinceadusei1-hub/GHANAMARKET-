"""Staff sign-in for the Control Centre: works, is protected, and stays staff-only."""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import views
from .models import User

PASSWORD = "A-strong-password-482!"
LOGIN = "/admin/login/"


class AdminLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.buyer = User.objects.create_user("ama", "ama@example.com", PASSWORD)

    def test_page_renders_new_design(self):
        page = self.client.get(LOGIN)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Staff sign in")
        self.assertContains(page, "Sign in to Control Centre")
        self.assertContains(page, 'autocomplete="current-password"')

    def test_staff_sign_in_goes_to_the_dashboard_or_next(self):
        response = self.client.post(LOGIN, {"username": "boss", "password": PASSWORD, "next": "/admin/review/"})
        self.assertRedirects(response, "/admin/review/", fetch_redirect_response=False)
        self.client.logout()
        response = self.client.post(LOGIN, {"username": "boss", "password": PASSWORD})
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

    def test_admin_pages_send_visitors_here(self):
        response = self.client.get("/admin/")
        self.assertTrue(response["Location"].startswith(LOGIN))

    def test_non_staff_accounts_are_refused(self):
        response = self.client.post(LOGIN, {"username": "ama", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "staff account")
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_already_signed_in_staff_skip_the_form(self):
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get(LOGIN), reverse("admin:index"), fetch_redirect_response=False)

    def test_password_guessing_is_blocked(self):
        for _ in range(views.LOGIN_FAILURES_PER_ACCOUNT):
            self.client.post(LOGIN, {"username": "boss", "password": "wrong-guess"})
        blocked = self.client.post(LOGIN, {"username": "boss", "password": PASSWORD})
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many sign-in attempts", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)
