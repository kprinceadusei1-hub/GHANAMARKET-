from datetime import timedelta

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Conversation, GhanaRegion, Message, Product, Promotion, SupportRequest, User

PASSWORD = "A-strong-password-482!"


class Fixtures(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD)
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)

    def listing(self, title, minutes_ago=0, **extra):
        product = Product.objects.create(
            seller=self.seller, title=title, description="x", category_id=extra.pop("category", "fashion"),
            price=extra.pop("price", "100"), city="Accra", region=GhanaRegion.GREATER_ACCRA,
            status=extra.pop("status", Product.Status.PUBLISHED), image="products/x.jpg", **extra,
        )
        Product.objects.filter(pk=product.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return product

    def promote(self, product, placement=Promotion.Placement.BOTH, **times):
        now = timezone.now()
        return Promotion.objects.create(
            product=product, placement=placement,
            starts_at=times.get("starts_at", now - timedelta(hours=1)),
            ends_at=times.get("ends_at", now + timedelta(days=7)),
        )


class PromotionTests(Fixtures):
    def test_promoted_listing_leads_homepage_and_is_labelled(self):
        older = self.listing("Older sandals", minutes_ago=60)
        self.listing("Newest sandals")
        self.promote(older, Promotion.Placement.HOMEPAGE)

        response = self.client.get(reverse("home"))

        featured = dict((key, items) for key, _, items in response.context["product_tabs"])["featured"]
        self.assertEqual(featured[0].title, "Older sandals")
        self.assertContains(response, "Promoted")

    def test_category_promotion_orders_browse_but_not_price_sorts(self):
        older = self.listing("Older dress", minutes_ago=60, price="500")
        self.listing("Newest dress", price="50")
        self.promote(older, Promotion.Placement.CATEGORY)

        browse = self.client.get(reverse("product_list"), {"category": "fashion"})
        self.assertEqual(browse.context["products"][0].title, "Older dress")
        by_price = self.client.get(reverse("product_list"), {"category": "fashion", "sort": "price-low"})
        self.assertEqual(by_price.context["products"][0].title, "Newest dress")

    def test_expired_or_stopped_promotions_have_no_effect(self):
        older = self.listing("Older bag", minutes_ago=60)
        self.listing("Newest bag")
        now = timezone.now()
        self.promote(older, starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=1))
        stopped = self.promote(older)
        stopped.is_active = False
        stopped.save()

        response = self.client.get(reverse("product_list"), {"category": "fashion"})

        self.assertEqual(response.context["products"][0].title, "Newest bag")
        self.assertNotContains(response, "promoted-label")

    def test_only_live_real_listings_can_be_promoted(self):
        pending = self.listing("Pending", status=Product.Status.PENDING)
        promo = Promotion(product=pending, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            promo.full_clean()

    def test_admin_records_who_created_a_promotion(self):
        product = self.listing("Phone")
        self.client.force_login(self.admin)
        now = timezone.localtime()
        response = self.client.post(reverse("admin:marketplace_promotion_add"), {
            "product": product.pk, "placement": "both", "fee": "0",
            "starts_at_0": now.strftime("%Y-%m-%d"), "starts_at_1": now.strftime("%H:%M:%S"),
            "ends_at_0": (now + timedelta(days=3)).strftime("%Y-%m-%d"), "ends_at_1": now.strftime("%H:%M:%S"),
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Promotion.objects.get().created_by, self.admin)
        self.assertIn("Promotions & Advertising", [g["label"] for g in self.client.get(reverse("admin:index")).context["cc_sidebar"]])


class UnreadMessageTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.product = self.listing("Phone")
        self.conversation = Conversation.objects.create(product=self.product, buyer=self.buyer, seller=self.seller)

    def send(self, sender, body):
        return Message.objects.create(conversation=self.conversation, sender=sender, body=body)

    def test_badge_counts_only_messages_from_the_other_person(self):
        self.send(self.buyer, "Is it available?")
        self.send(self.buyer, "Hello?")
        self.client.force_login(self.seller)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["unread_messages"], 2)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("home")).context["unread_messages"], 0)

    def test_opening_the_thread_marks_it_read(self):
        self.send(self.buyer, "Is it available?")
        self.client.force_login(self.seller)
        inbox = self.client.get(reverse("conversation_list"))
        self.assertEqual(inbox.context["conversations"][0].unread, 1)
        self.assertContains(inbox, "is-unread")

        self.client.get(reverse("conversation_detail", args=[self.conversation.pk]))

        self.assertEqual(self.client.get(reverse("home")).context["unread_messages"], 0)
        self.assertEqual(self.client.get(reverse("conversation_list")).context["conversations"][0].unread, 0)

    def test_new_reply_after_reading_is_unread_again(self):
        self.send(self.buyer, "First")
        self.client.force_login(self.seller)
        self.client.get(reverse("conversation_detail", args=[self.conversation.pk]))
        second = self.send(self.buyer, "Second")
        Message.objects.filter(pk=second.pk).update(created_at=timezone.now() + timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse("home")).context["unread_messages"], 1)


class PulseTests(Fixtures):
    def test_pulse_returns_live_counts_for_permitted_queues(self):
        SupportRequest.objects.create(email="a@example.com", topic="other", subject="Hi", message="Help")
        self.client.force_login(self.admin)
        data = self.client.get(reverse("marketplace_admin_pulse")).json()
        self.assertEqual(data["queues"]["support"], 1)
        self.assertEqual(data["total"], 1)

        staff = User.objects.create_user("helper", "h@example.com", PASSWORD, is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_supportrequest"))
        self.client.force_login(staff)
        self.assertEqual(list(self.client.get(reverse("marketplace_admin_pulse")).json()["queues"]), ["support"])

    def test_pulse_requires_staff(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("marketplace_admin_pulse")).status_code, 302)
