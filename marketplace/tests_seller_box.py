from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import normalise_ghana_card
from .models import Conversation, GhanaRegion, Message, Notification, Product, SellerVerification, User
from . import moderation, trust

PASSWORD = "A-strong-password-482!"


class GhanaCardTests(TestCase):
    def test_number_is_normalised_or_rejected(self):
        self.assertEqual(normalise_ghana_card("gha 123456789 0"), "GHA-123456789-0")
        self.assertEqual(normalise_ghana_card("GHA-123456789-0"), "GHA-123456789-0")
        self.assertEqual(normalise_ghana_card("1234567890"), "GHA-123456789-0")
        self.assertIsNone(normalise_ghana_card("GHA-12345-0"))
        self.assertIsNone(normalise_ghana_card("hello"))

    def test_new_seller_goes_to_ghana_card_step_and_cannot_be_approved_without_it(self):
        response = self.client.post(reverse("register"), {
            "username": "kojo", "email": "kojo@example.com", "role": "seller", "phone_number": "0240000000",
            "city": "Kumasi", "region": GhanaRegion.ASHANTI, "password1": PASSWORD, "password2": PASSWORD,
        }, follow=True)
        self.assertContains(response, "Add your Ghana Card")
        self.assertContains(response, "Step 2 of 2")
        seller = User.objects.get(username="kojo")
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        with self.assertRaises(moderation.ModerationError):
            moderation.approve_seller(seller, admin)
        SellerVerification.objects.create(user=seller, kind="ghana_card", legal_name="Kojo",
                                          document_number="GHA-123456789-0", document="verifications/x.pdf")
        moderation.approve_seller(seller, admin)
        seller.refresh_from_db()
        self.assertTrue(seller.can_sell)
        self.assertFalse(seller.is_verified_seller)  # the badge is a separate staff decision

    def test_dashboard_banner_until_card_is_added(self):
        seller = User.objects.create_user("efua", "efua@example.com", PASSWORD, phone_number="0240000000")
        seller.request_seller_approval()
        seller.save()
        self.client.force_login(seller)
        self.assertContains(self.client.get(reverse("seller_listings")), "Add your Ghana Card to finish")


class SellerBoxTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER,
                                               first_name="Selina", phone_number="0241112222")
        User.objects.filter(pk=self.seller.pk).update(date_joined=timezone.now() - timedelta(days=400))
        self.seller.refresh_from_db()
        self.product = Product.objects.create(seller=self.seller, title="Dress", description="x",
                                              category_id="fashion", price="240", city="Accra",
                                              region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD, first_name="Ama")
        self.url = reverse("product_detail", args=[self.product.pk])

    def test_box_shows_real_tenure_and_verified_only_when_true(self):
        response = self.client.get(self.url)
        self.assertContains(response, "1+ year on GhanaMarket")
        self.assertNotContains(response, "seller-badge-verified")
        self.assertContains(response, "No feedback yet")
        self.assertContains(response, "Show contact")
        self.assertContains(response, "Start chat")
        self.assertContains(response, "Request call back")
        User.objects.filter(pk=self.seller.pk).update(verified_at=timezone.now())
        self.assertContains(self.client.get(self.url), "seller-badge-verified")

    def test_reply_speed_needs_enough_real_chats(self):
        self.assertIsNone(trust.seller_reply_speed(self.seller))
        for i in range(3):
            buyer = User.objects.create_user(f"b{i}", f"b{i}@example.com", PASSWORD)
            chat = Conversation.objects.create(product=self.product, buyer=buyer, seller=self.seller)
            Message.objects.create(conversation=chat, sender=buyer, body="Available?")
            Message.objects.create(conversation=chat, sender=self.seller, body="Yes")
        cache.clear()
        self.assertEqual(trust.seller_reply_speed(self.seller), "Replies within an hour")

    def test_request_call_back_sends_number_to_seller(self):
        self.client.force_login(self.buyer)
        url = reverse("request_callback", args=[self.product.pk])
        response = self.client.post(url, {"phone": "12"}, follow=True)
        self.assertContains(response, "Enter your Ghana phone number")
        response = self.client.post(url, {"phone": "020 555 6666"}, follow=True)
        self.assertContains(response, "The seller has your number")
        message = Message.objects.get()
        self.assertIn("020 555 6666", message.body)
        self.assertEqual(message.conversation.seller, self.seller)
        self.assertTrue(Notification.objects.filter(user=self.seller, title="Call-back request").exists())

    def test_own_listing_has_no_save_or_contact_buttons(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertContains(response, "Edit listing")
        self.assertNotContains(response, "Show contact")
        self.assertNotContains(response, "Request call back")
        self.assertNotContains(response, 'action="/listings/%d/favorite/"' % self.product.pk)
