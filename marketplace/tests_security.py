from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Conversation, GhanaRegion, Product, User
from .views import LOGIN_FAILURES_PER_ACCOUNT, MESSAGES_PER_WINDOW

PASSWORD = "A-strong-password-482!"


def make_users():
    seller = User.objects.create_user(
        username="seller", email="seller@example.com", password=PASSWORD,
        role=User.Role.SELLER, city="Accra", region=GhanaRegion.GREATER_ACCRA, phone_number="0240000000",
    )
    buyer = User.objects.create_user(
        username="buyer", email="buyer@example.com", password=PASSWORD, role=User.Role.BUYER,
    )
    return seller, buyer


def make_product(seller, **overrides):
    values = {
        "seller": seller, "title": "Handmade basket", "description": "Woven in Ghana.",
        "category_id": Product.Category.HOME_LIVING, "price": "45.00", "city": "Accra",
        "region": GhanaRegion.GREATER_ACCRA, "status": Product.Status.PUBLISHED,
    }
    values.update(overrides)
    return Product.objects.create(**values)


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller, self.buyer = make_users()

    def test_account_is_locked_after_repeated_failures_even_with_correct_password(self):
        for _ in range(LOGIN_FAILURES_PER_ACCOUNT):
            self.client.post(reverse("login"), {"username": "buyer", "password": "wrong"})

        response = self.client.post(reverse("login"), {"username": "buyer", "password": PASSWORD})

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many sign-in attempts", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_failure_count(self):
        for _ in range(LOGIN_FAILURES_PER_ACCOUNT - 1):
            self.client.post(reverse("login"), {"username": "buyer", "password": "wrong"})
        self.client.post(reverse("login"), {"username": "buyer", "password": PASSWORD})
        self.client.logout()

        self.client.post(reverse("login"), {"username": "buyer", "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": "buyer", "password": PASSWORD})

        self.assertEqual(response.status_code, 302)

    def test_login_page_links_to_password_reset(self):
        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller, self.buyer = make_users()

    def test_reset_email_is_sent_for_registered_address(self):
        response = self.client.post(reverse("password_reset"), {"email": "buyer@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)

    def test_unknown_address_gets_same_response_without_email(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_sets_new_password(self):
        self.client.post(reverse("password_reset"), {"email": "buyer@example.com"})
        link = next(line for line in mail.outbox[0].body.splitlines() if "/accounts/reset/" in line)
        path = link[link.index("/accounts/reset/"):]

        form_page = self.client.get(path, follow=True)
        response = self.client.post(form_page.redirect_chain[-1][0], {
            "new_password1": "Another-strong-pass-913",
            "new_password2": "Another-strong-pass-913",
        })

        self.assertRedirects(response, reverse("password_reset_complete"))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password("Another-strong-pass-913"))


class MessagingThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller, self.buyer = make_users()
        self.product = make_product(self.seller)

    def test_message_flood_is_blocked(self):
        self.client.force_login(self.buyer)
        url = reverse("conversation_start", args=[self.product.pk])
        self.client.post(url, {"body": "Is it available?"})
        conversation = Conversation.objects.get()
        reply_url = reverse("conversation_detail", args=[conversation.pk])
        for _ in range(MESSAGES_PER_WINDOW - 1):
            self.client.post(reply_url, {"body": "Hello"})

        response = self.client.post(reply_url, {"body": "One too many"}, follow=True)

        self.assertContains(response, "sending messages too quickly")
        self.assertEqual(conversation.messages.count(), MESSAGES_PER_WINDOW)


class ListingDeletionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller, self.buyer = make_users()
        self.other_seller = User.objects.create_user(
            username="other", email="other@example.com", password=PASSWORD, role=User.Role.SELLER,
        )

    def test_seller_can_delete_listing_without_linked_records(self):
        product = make_product(self.seller, status=Product.Status.DRAFT)
        self.client.force_login(self.seller)

        response = self.client.post(reverse("seller_listing_status", args=[product.pk]), {"action": "delete"})

        self.assertRedirects(response, reverse("seller_listings"))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_listing_with_conversation_cannot_be_deleted(self):
        product = make_product(self.seller)
        Conversation.objects.create(product=product, buyer=self.buyer, seller=self.seller)
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("seller_listing_status", args=[product.pk]), {"action": "delete"}, follow=True,
        )

        self.assertContains(response, "cannot be deleted")
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_seller_cannot_delete_another_sellers_listing(self):
        product = make_product(self.seller)
        self.client.force_login(self.other_seller)

        response = self.client.post(reverse("seller_listing_status", args=[product.pk]), {"action": "delete"})

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
