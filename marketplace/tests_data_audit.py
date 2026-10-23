"""Regression tests for the final listings / data-integrity audit fixes."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from commerce import services
from commerce.models import DeliveryOption, Order

from . import moderation, trust
from .catalog import categories_with_counts
from .forms import ProductForm
from .models import (
    Category, CategoryAttribute, Conversation, GhanaRegion, Product, ProhibitedTerm, SellerVerification, User,
)

PASSWORD = "A-strong-password-482!"


def listing(seller, **extra):
    data = dict(seller=seller, title="Item", description="x", category_id="phones-tech", price="100",
                city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED)
    data.update(extra)
    return Product.objects.create(**data)


@override_settings(DEBUG=True, PAYMENT_PROVIDER="test")
class DeletionWithOpenOrdersTests(TestCase):
    def test_cannot_delete_while_a_payment_is_in_progress(self):
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD)
        product = listing(seller, allows_checkout=True, stock_quantity=2)
        services.add_to_cart(buyer, product, 1)
        checkout = services.create_checkout(buyer, {seller.pk: DeliveryOption.objects.get(kind="pickup")})
        self.assertEqual(checkout.orders.get().status, Order.Status.PENDING_PAYMENT)
        with self.assertRaises(trust.AccountDeletionBlocked):
            trust.delete_account(seller)
        with self.assertRaises(trust.AccountDeletionBlocked):
            trust.delete_account(buyer)


class RejectedCardPausesSellerTests(TestCase):
    def test_seller_approved_on_pending_card_is_paused_when_card_rejected(self):
        staff = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        seller = User.objects.create_user("ama", "ama@example.com", PASSWORD, phone_number="0241234567")
        seller.request_seller_approval()
        seller.save()
        card = SellerVerification.objects.create(user=seller, kind="ghana_card", legal_name="Ama",
                                                 document_number="GHA-123456789-0", document="verifications/a.jpg")
        moderation.approve_seller(seller, staff)
        moderation.decide_verification(card, staff, False, "The photo is blurry.")
        seller.refresh_from_db()
        self.assertEqual(seller.seller_status, User.SellerStatus.PENDING)
        self.assertFalse(seller.can_sell)

    def test_legacy_seller_without_application_is_not_paused(self):
        staff = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        seller = User.objects.create_user("old", "old@example.com", PASSWORD, role=User.Role.SELLER)
        card = SellerVerification.objects.create(user=seller, kind="ghana_card", legal_name="Old",
                                                 document_number="GHA-123456789-0", document="verifications/a.jpg")
        moderation.decide_verification(card, staff, False, "Blurry")
        seller.refresh_from_db()
        self.assertTrue(seller.can_sell)


class CountsExcludePreviewsTests(TestCase):
    def test_category_counts_are_real_ads_only(self):
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        listing(seller)
        listing(seller, is_demo=True)
        counts = {row["value"]: row["count"] for row in categories_with_counts()}
        self.assertEqual(counts["phones-tech"], 1)
        self.assertEqual(self.client.get(reverse("home")).context["listing_count"], 1)


class SubcategoryAttributeTests(TestCase):
    def test_subcategory_attributes_are_required_on_the_form(self):
        mobile = Category.objects.get(slug="mobile-phones")
        CategoryAttribute.objects.create(category=mobile, key="imei_checked", label="IMEI checked",
                                         kind=CategoryAttribute.Kind.TEXT, is_required=True)
        phones = Category.objects.get(slug="phones-tech")
        form = ProductForm(initial={"category": phones, "subcategory": mobile}, category=phones)
        self.assertIn("attr_imei_checked", form.fields)
        top_only = ProductForm(initial={"category": phones}, category=phones)
        self.assertNotIn("attr_imei_checked", top_only.fields)


class AdminSafetyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(self.admin)
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.product = listing(seller)

    def test_products_cannot_be_hard_deleted(self):
        url = reverse("admin:marketplace_product_delete", args=[self.product.pk])
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_category_slug_locked_once_used(self):
        phones = Category.objects.get(slug="phones-tech")
        page = self.client.get(reverse("admin:marketplace_category_change", args=[phones.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="slug"')


class AttributeDisplayTests(TestCase):
    def test_text_value_in_number_attribute_does_not_crash(self):
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        phones = Category.objects.get(slug="phones-tech")
        CategoryAttribute.objects.create(category=phones, key="battery", label="Battery", unit="mAh",
                                         kind=CategoryAttribute.Kind.NUMBER)
        product = listing(seller, attributes={"battery": "about 5000"})
        self.assertIn(("Battery", "about 5000 mAh"), product.attribute_items())
        self.assertEqual(self.client.get(reverse("product_detail", args=[product.pk])).status_code, 200)


class ProhibitedIncludedItemsTests(TestCase):
    def test_blocked_word_in_included_items_is_refused(self):
        ProhibitedTerm.objects.create(term="cocaine", action=ProhibitedTerm.Action.BLOCK)
        self.assertIsNotNone(trust.blocked_listing_reason("Phone", "Nice", included="charger and cocaine"))


class InactiveChatTests(TestCase):
    def test_no_messages_to_a_deleted_account(self):
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD)
        chat = Conversation.objects.create(product=listing(seller), buyer=buyer, seller=seller)
        User.objects.filter(pk=seller.pk).update(is_active=False)
        self.client.force_login(buyer)
        self.client.post(reverse("conversation_detail", args=[chat.pk]), {"body": "Hello?"})
        self.assertFalse(chat.messages.exists())
