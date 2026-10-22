import shutil
import tempfile

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from commerce import services
from commerce.models import DeliveryOption, Order
from commerce.payments import VerificationResult
from commerce.payments.test_provider import TestProvider

from .models import (
    Conversation, GhanaRegion, Notification, Product, ProhibitedTerm, SellerReview, SellerVerification,
    SupportRequest, User, UserBlock, UserReport,
)
from .tests import sample_product_image

PASSWORD = "A-strong-password-482!"
PRIVATE_ROOT = tempfile.mkdtemp(prefix="marketplace-test-private-")


def jpeg_upload(name="card.jpg"):
    return SimpleUploadedFile(name, sample_product_image().read(), content_type="image/jpeg")


@override_settings(PRIVATE_MEDIA_ROOT=PRIVATE_ROOT, DEBUG=True, PAYMENT_PROVIDER="test")
class TrustFixtures(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVATE_ROOT, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.seller = self.make_user("seller", User.Role.SELLER)
        self.buyer = self.make_user("buyer", User.Role.BUYER)
        self.staff = User.objects.create_user(
            username="staff", email="staff@example.com", password=PASSWORD, is_staff=True,
        )
        self.product = Product.objects.create(
            seller=self.seller, title="Samsung phone", description="Works well.", category_id="phones-tech",
            price="900.00", city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED,
            allows_checkout=True, stock_quantity=2,
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, email=f"{username}@example.com", password=PASSWORD, role=role,
            phone_number="0240000000", city="Accra", region=GhanaRegion.GREATER_ACCRA, first_name=username.title(),
        )

    def listing_post(self, **overrides):
        data = {
            "title": "Plain wooden chair", "category": "home-living", "condition": Product.Condition.GOOD,
            "price": "150", "description": "Solid chair.", "region": GhanaRegion.GREATER_ACCRA, "city": "Accra",
            "images": [sample_product_image()],
        }
        data.update(overrides)
        return data


class ListingRiskTests(TrustFixtures):
    def test_blocked_term_rejects_listing_with_reason(self):
        ProhibitedTerm.objects.create(term="pistol", action=ProhibitedTerm.Action.BLOCK, reason="Weapons are not allowed.")
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), self.listing_post(title="Pistol for sale"))
        self.assertContains(response, "Weapons are not allowed.")
        self.assertFalse(Product.objects.filter(title="Pistol for sale").exists())

    def test_partial_words_do_not_trigger_terms(self):
        ProhibitedTerm.objects.create(term="gun", action=ProhibitedTerm.Action.BLOCK)
        self.client.force_login(self.seller)
        self.client.post(reverse("product_create"), self.listing_post(title="Burgundy sofa"))
        self.assertTrue(Product.objects.filter(title="Burgundy sofa").exists())

    def test_flag_terms_and_duplicates_are_recorded_for_moderators(self):
        ProhibitedTerm.objects.create(term="replica", action=ProhibitedTerm.Action.FLAG)
        self.client.force_login(self.seller)
        self.client.post(reverse("product_create"), self.listing_post(title="Samsung phone", description="Replica box"))
        product = Product.objects.filter(title="Samsung phone").latest("pk")
        self.assertIn("Flagged words: replica", product.risk_flags)
        self.assertIn("Possible duplicate", product.risk_flags)
        self.client.force_login(self.buyer)
        self.assertNotContains(self.client.get(reverse("product_list")), "Flagged words")


class VerificationTests(TrustFixtures):
    def submit(self, **overrides):
        data = {"kind": "ghana_card", "legal_name": "Kofi Mensah", "document_number": "GHA-123456789-1",
                "document": jpeg_upload(), "confirm": "on"}
        data.update(overrides)
        return self.client.post(reverse("seller_verification"), data)

    def test_seller_submits_and_staff_approval_grants_badge(self):
        self.client.force_login(self.seller)
        self.submit()
        verification = SellerVerification.objects.get()
        self.assertEqual(verification.status, SellerVerification.Status.PENDING)
        self.seller.refresh_from_db()
        self.assertFalse(self.seller.is_verified_seller)
        self.assertNotContains(self.client.get(reverse("product_detail", args=[self.product.pk])), "Verified seller")

        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=(
            "view_sellerverification", "change_sellerverification")))
        self.client.force_login(self.staff)
        self.client.post(reverse("admin:marketplace_sellerverification_changelist"), {
            "action": "approve", "_selected_action": [verification.pk],
        })
        self.seller.refresh_from_db()
        self.assertTrue(self.seller.is_verified_seller)
        self.assertContains(self.client.get(reverse("product_detail", args=[self.product.pk])), "Verified seller")
        self.assertTrue(Notification.objects.filter(user=self.seller, title__contains="verified seller").exists())

    def test_rejecting_removes_badge(self):
        self.client.force_login(self.seller)
        self.submit()
        verification = SellerVerification.objects.get()
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=(
            "view_sellerverification", "change_sellerverification")))
        self.client.force_login(self.staff)
        url = reverse("admin:marketplace_sellerverification_changelist")
        self.client.post(url, {"action": "approve", "_selected_action": [verification.pk]})
        self.client.post(url, {"action": "reject", "_selected_action": [verification.pk]})
        self.seller.refresh_from_db()
        self.assertFalse(self.seller.is_verified_seller)

    def test_non_document_upload_is_rejected(self):
        self.client.force_login(self.seller)
        response = self.submit(document=SimpleUploadedFile("card.jpg", b"<script>x</script>", content_type="image/jpeg"))
        self.assertContains(response, "does not look like a PDF or image")
        self.assertFalse(SellerVerification.objects.exists())

    def test_documents_are_never_public(self):
        self.client.force_login(self.seller)
        self.submit()
        verification = SellerVerification.objects.get()
        self.assertNotIn("/media/", verification.document.path.replace("\\", "/"))
        url = reverse("verification_document", args=[verification.pk])
        self.assertEqual(self.client.get(url).status_code, 302)  # sellers are sent to the admin login
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 404)  # staff without permission
        self.staff.user_permissions.add(Permission.objects.get(codename="view_sellerverification"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_buyers_cannot_request_verification(self):
        self.client.force_login(self.buyer)
        self.assertRedirects(self.client.get(reverse("seller_verification")), reverse("become_seller"))

    def test_verified_filter(self):
        other = self.make_user("other", User.Role.SELLER)
        Product.objects.create(seller=other, title="Other phone", description="x", category_id="phones-tech",
                               price="10", city="Accra", status=Product.Status.PUBLISHED)
        User.objects.filter(pk=self.seller.pk).update(verified_at="2026-10-01T10:00:00Z")
        response = self.client.get(reverse("product_list"), {"verified": "1"})
        self.assertEqual([p.title for p in response.context["products"]], ["Samsung phone"])


class ReviewTests(TrustFixtures):
    def completed_order(self):
        services.add_to_cart(self.buyer, self.product)
        checkout = services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))
        order = checkout.orders.get()
        services.change_order_status(order, Order.Status.READY_FOR_PICKUP, self.seller)
        return order

    def test_review_only_after_completion_and_only_once(self):
        order = self.completed_order()
        self.client.force_login(self.buyer)
        url = reverse("review_order", args=[order.number])
        self.client.post(url, {"rating": 5, "comment": "Great"})
        self.assertFalse(SellerReview.objects.exists())

        services.change_order_status(order, Order.Status.COMPLETED, self.buyer)
        self.client.post(url, {"rating": 4, "comment": "Smooth handover"})
        self.client.post(url, {"rating": 1, "comment": "Second try"})
        self.assertEqual(SellerReview.objects.get().rating, 4)
        storefront = self.client.get(reverse("seller_storefront", args=[self.seller.pk]))
        self.assertContains(storefront, "Smooth handover")
        self.assertContains(storefront, "4.0")

    def test_no_rating_shown_until_earned(self):
        storefront = self.client.get(reverse("seller_storefront", args=[self.seller.pk]))
        self.assertIsNone(storefront.context["seller_rating"])
        self.assertNotContains(storefront, 'class="rating"')
        self.assertNotContains(storefront, "Reviews from buyers")


class BlockAndReportTests(TrustFixtures):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(product=self.product, buyer=self.buyer, seller=self.seller)

    def test_block_stops_messages_both_ways_until_unblocked(self):
        self.client.force_login(self.seller)
        self.client.post(reverse("toggle_block", args=[self.buyer.pk]))
        self.assertTrue(UserBlock.objects.filter(blocker=self.seller, blocked=self.buyer).exists())

        self.client.force_login(self.buyer)
        self.client.post(reverse("conversation_detail", args=[self.conversation.pk]), {"body": "Hello?"})
        self.client.post(reverse("conversation_start", args=[self.product.pk]), {"body": "Hello again"})
        self.assertEqual(self.conversation.messages.count(), 0)

        self.client.force_login(self.seller)
        self.client.post(reverse("toggle_block", args=[self.buyer.pk]))
        self.client.force_login(self.buyer)
        self.client.post(reverse("conversation_detail", args=[self.conversation.pk]), {"body": "Hello?"})
        self.assertEqual(self.conversation.messages.count(), 1)

    def test_cannot_block_staff_or_self(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(reverse("toggle_block", args=[self.staff.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("toggle_block", args=[self.buyer.pk])).status_code, 404)

    def test_report_user_once_and_no_open_redirect(self):
        self.client.force_login(self.buyer)
        url = reverse("report_user", args=[self.seller.pk])
        response = self.client.post(url, {"reason": "scam", "next": "//evil.example.com/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.client.post(url, {"reason": "scam"})
        self.assertEqual(UserReport.objects.count(), 1)


class HelpAndSupportTests(TrustFixtures):
    def test_help_pages_render(self):
        for slug in ("", "safety", "buying", "selling", "prohibited-items", "refunds", "fees", "privacy", "terms"):
            url = reverse("help_page", args=[slug]) if slug else reverse("help")
            self.assertEqual(self.client.get(url).status_code, 200, slug)
        self.assertEqual(self.client.get("/help/not-a-page/").status_code, 404)

    def test_anonymous_appeal_is_saved_and_throttled(self):
        data = {"email": "me@example.com", "topic": "appeal", "subject": "Please review", "message": "I was suspended."}
        for _ in range(5):
            self.client.post(reverse("contact_support"), data)
        response = self.client.post(reverse("contact_support"), data)
        self.assertEqual(SupportRequest.objects.filter(topic="appeal").count(), 5)
        self.assertContains(response, "Too many requests")

    def test_notification_links_cannot_leave_the_site(self):
        self.client.force_login(self.buyer)
        for url in ("https://evil.example.com", "//evil.example.com", "/\\evil.example.com"):
            note = Notification.objects.create(user=self.buyer, title="x", url=url)
            response = self.client.get(reverse("notification_open", args=[note.pk]))
            self.assertRedirects(response, reverse("notification_list"))


class AccountDeletionTests(TrustFixtures):
    def test_deletion_anonymises_and_hides_listings(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("delete_account"), {"password": PASSWORD})
        self.assertRedirects(response, reverse("home"))
        self.seller.refresh_from_db()
        self.product.refresh_from_db()
        self.assertFalse(self.seller.is_active)
        self.assertEqual(self.seller.email, f"deleted-{self.seller.pk}@deleted.invalid")
        self.assertEqual(self.seller.phone_number, "")
        self.assertEqual(self.product.status, Product.Status.DRAFT)
        self.assertFalse(self.client.login(username="seller", password=PASSWORD))

    def test_wrong_password_or_open_orders_block_deletion(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("delete_account"), {"password": "wrong"})
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_active)

        services.add_to_cart(self.buyer, self.product)
        checkout = services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))
        response = self.client.post(reverse("delete_account"), {"password": PASSWORD}, follow=True)
        self.assertContains(response, "open orders")
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_active)


class RateLimitTests(TrustFixtures):
    def test_registration_is_throttled_per_ip(self):
        from .views import REGISTRATIONS_PER_HOUR

        for _ in range(REGISTRATIONS_PER_HOUR):
            self.client.post(reverse("register"), {"username": ""})
        response = self.client.post(reverse("register"), {"username": ""})
        self.assertEqual(response.status_code, 429)
