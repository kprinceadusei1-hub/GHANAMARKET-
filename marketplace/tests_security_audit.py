"""Regression tests for the final security audit fixes."""
import io

from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from . import throttling, trust
from .images import normalise_upload
from .models import GhanaRegion, Product, SellerVerification, User

PASSWORD = "A-strong-password-482!"


def staff_with(*codenames, username="mod"):
    user = User.objects.create_user(username, f"{username}@example.com", PASSWORD, is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return user


class DisguisedDocumentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)

    def test_html_disguised_as_pdf_is_stored_and_served_safely(self):
        self.client.force_login(self.seller)
        upload = SimpleUploadedFile("card.html", b"%PDF<script>alert(1)</script>", content_type="application/pdf")
        self.client.post(reverse("seller_verification"), {
            "kind": "ghana_card", "legal_name": "Kofi", "document_number": "GHA-123456789-0",
            "document": upload, "confirm": "on",
        })
        verification = SellerVerification.objects.get()
        self.assertTrue(verification.document.name.endswith(".pdf"))
        self.assertNotIn("card", verification.document.name)
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(admin)
        response = self.client.get(reverse("verification_document", args=[verification.pk]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("sandbox", response["Content-Security-Policy"])

    def test_unknown_stored_extension_downloads_instead_of_rendering(self):
        verification = SellerVerification.objects.create(
            user=self.seller, kind="ghana_card", legal_name="Kofi", document_number="GHA-123456789-0",
            document=SimpleUploadedFile("old.html", b"<script>alert(1)</script>"))
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(admin)
        response = self.client.get(reverse("verification_document", args=[verification.pk]))
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertEqual(response["Content-Disposition"], "attachment")


class AdminPrivilegeTests(TestCase):
    def test_staff_cannot_make_themselves_superuser(self):
        moderator = staff_with("view_user", "change_user")
        self.client.force_login(moderator)
        url = reverse("admin:marketplace_user_change", args=[moderator.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="is_superuser"')
        self.assertNotContains(page, 'name="user_permissions"')
        self.client.post(url, {
            "username": "mod", "email": "mod@example.com", "is_superuser": "on", "is_staff": "on",
            "role": "buyer", "seller_status": "approved", "country": "GH",
            "date_joined_0": "2026-01-01", "date_joined_1": "10:00:00",
        })
        moderator.refresh_from_db()
        self.assertFalse(moderator.is_superuser)

    def test_staff_cannot_edit_or_reset_a_superuser(self):
        boss = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        moderator = staff_with("view_user", "change_user")
        self.client.force_login(moderator)
        password_url = reverse("admin:auth_user_password_change", args=[boss.pk])
        response = self.client.post(password_url, {"password1": "Hacked-password-123!",
                                                   "password2": "Hacked-password-123!"})
        self.assertEqual(response.status_code, 403)
        boss.refresh_from_db()
        self.assertTrue(boss.check_password(PASSWORD))

    def test_view_only_staff_get_no_state_changing_actions(self):
        viewer = staff_with("view_user", "view_listingreport", username="viewer")
        self.client.force_login(viewer)
        users = self.client.get(reverse("admin:marketplace_user_changelist"))
        self.assertNotContains(users, "suspend_member_accounts")
        reports = self.client.get(reverse("admin:marketplace_listingreport_changelist"))
        self.assertNotContains(reports, "remove_reported_listings")
        self.assertNotContains(reports, "dismiss_reports")


class SuspendedSellerTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.product = Product.objects.create(
            seller=self.seller, title="Fake iPhone", description="x", category_id="phones-tech", price="100",
            city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED,
            allows_checkout=True, stock_quantity=3)

    def test_suspending_hides_ads_and_stops_sales(self):
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(admin)
        self.client.post(reverse("admin:marketplace_user_changelist"), {
            "action": "suspend_member_accounts", "_selected_action": [self.seller.pk]})
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.DRAFT)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("product_detail", args=[self.product.pk])).status_code, 404)

    def test_inactive_seller_listing_cannot_be_bought_even_if_published(self):
        User.objects.filter(pk=self.seller.pk).update(is_active=False)
        product = Product.objects.select_related("seller", "category").get(pk=self.product.pk)
        self.assertFalse(product.can_checkout)
        self.assertNotContains(self.client.get(reverse("product_list")), "Fake iPhone")


class ClientIpTests(TestCase):
    @override_settings(TRUST_X_FORWARDED_FOR=True, TRUSTED_PROXY_COUNT=1)
    def test_forged_left_entries_are_ignored(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 41.66.0.9", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(throttling.client_ip(request), "41.66.0.9")

    def test_header_ignored_unless_trusted(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(throttling.client_ip(request), "10.0.0.1")


class PasswordResetEmailLimitTests(TestCase):
    def test_one_address_cannot_be_flooded_from_many_ips(self):
        cache.clear()
        User.objects.create_user("ama", "ama@example.com", PASSWORD)
        for index in range(6):
            self.client.post(reverse("password_reset"), {"email": "ama@example.com"}, REMOTE_ADDR=f"10.0.0.{index}")
        self.assertEqual(len(mail.outbox), 3)


class DeletionPrivacyTests(TestCase):
    def test_deleting_account_removes_identity_document(self):
        user = User.objects.create_user("ama", "ama@example.com", PASSWORD, role=User.Role.SELLER)
        verification = SellerVerification.objects.create(
            user=user, kind="ghana_card", legal_name="Ama Mensah", document_number="GHA-123456789-0",
            document=SimpleUploadedFile("id.pdf", b"%PDF-1.4"))
        trust.delete_account(user)
        verification.refresh_from_db()
        self.assertEqual(verification.document_number, "[deleted]")
        self.assertEqual(verification.legal_name, "[deleted]")
        self.assertFalse(verification.document)


class CardNumberVisibilityTests(TestCase):
    def test_seller_tab_hides_card_without_verification_permission(self):
        applicant = User.objects.create_user("ama", "ama@example.com", PASSWORD, phone_number="0241234567")
        applicant.request_seller_approval()
        applicant.save()
        SellerVerification.objects.create(user=applicant, kind="ghana_card", legal_name="Ama",
                                          document_number="GHA-987654321-0", document="verifications/a.jpg")
        moderator = staff_with("view_user", "change_user")
        self.client.force_login(moderator)
        response = self.client.get(reverse("marketplace_review_centre"), {"tab": "sellers"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "GHA-987654321-0")


class ImageBombTests(TestCase):
    def test_oversized_dimensions_are_refused(self):
        buffer = io.BytesIO()
        Image.new("1", (8000, 6000)).save(buffer, format="PNG")
        buffer.name = "huge.png"
        with self.assertRaises(ValueError):
            normalise_upload(buffer)
