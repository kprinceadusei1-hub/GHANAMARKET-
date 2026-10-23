from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Conversation, GhanaRegion, Message, Product, User

PASSWORD = "A-strong-password-482!"
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class LiveChatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD)
        self.product = Product.objects.create(seller=self.seller, title="Fan", description="x",
                                              category_id="home-living", price="100", city="Accra",
                                              region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED)
        self.chat = Conversation.objects.create(product=self.product, buyer=self.buyer, seller=self.seller)
        self.detail = reverse("conversation_detail", args=[self.chat.pk])
        self.poll = reverse("conversation_poll", args=[self.chat.pk])

    def test_send_without_reload_returns_the_message(self):
        self.client.force_login(self.buyer)
        response = self.client.post(self.detail, {"body": "Is it available?"}, **FETCH)
        self.assertEqual(response.status_code, 201)
        data = response.json()["message"]
        self.assertEqual(data["body"], "Is it available?")
        self.assertTrue(data["mine"])
        self.assertEqual(self.client.post(self.detail, {"body": "  "}, **FETCH).status_code, 400)

    def test_poll_delivers_new_messages_and_read_receipts(self):
        first = Message.objects.create(conversation=self.chat, sender=self.buyer, body="Hello")
        self.client.force_login(self.seller)
        data = self.client.get(self.poll, {"after": 0}).json()
        self.assertEqual([m["body"] for m in data["messages"]], ["Hello"])
        self.assertFalse(data["messages"][0]["mine"])
        self.assertEqual(self.client.get(self.poll, {"after": first.pk}).json()["messages"], [])
        # The seller opening the chat is the buyer's "Seen" receipt.
        self.client.force_login(self.buyer)
        self.assertIsNotNone(self.client.get(self.poll, {"after": first.pk}).json()["seen_until"])

    def test_unread_badge_endpoint(self):
        Message.objects.create(conversation=self.chat, sender=self.buyer, body="Hello")
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("unread_counts")).json()["messages"], 1)
        self.client.get(self.poll, {"after": 0})
        self.assertEqual(self.client.get(reverse("unread_counts")).json()["messages"], 0)

    def test_outsiders_and_blocked_people_cannot_use_it(self):
        outsider = User.objects.create_user("x", "x@example.com", PASSWORD)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.poll).status_code, 404)
        self.assertEqual(self.client.post(self.detail, {"body": "hi"}, **FETCH).status_code, 404)
        self.buyer.blocks_made.create(blocked=self.seller)
        self.client.force_login(self.buyer)
        response = self.client.post(self.detail, {"body": "hi"}, **FETCH)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_a_seller_can_message_another_seller(self):
        other_seller = User.objects.create_user("shop2", "shop2@example.com", PASSWORD, role=User.Role.SELLER)
        self.client.force_login(other_seller)
        self.assertContains(self.client.get(reverse("product_detail", args=[self.product.pk])), "Start chat")
        response = self.client.post(reverse("conversation_start", args=[self.product.pk]), {"body": "Wholesale price?"})
        conversation = Conversation.objects.get(buyer=other_seller)
        self.assertRedirects(response, reverse("conversation_detail", args=[conversation.pk]))
