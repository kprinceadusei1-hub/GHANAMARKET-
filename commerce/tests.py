import hashlib
import hmac
import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from marketplace.models import GhanaRegion, Notification, Product, User

from . import services
from .models import Address, CartItem, Checkout, DeliveryOption, Order, OrderIssue, Payment, PaymentEvent, Refund
from .payments import VerificationResult, get_provider
from .payments.paystack import PaystackProvider
from .payments.test_provider import OUTCOME_KEY, TestProvider

PASSWORD = "A-strong-password-482!"
SECRET = "sk_test_secret_for_tests"


@override_settings(DEBUG=True, PAYMENT_PROVIDER="test")
class CommerceFixtures(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = self.make_user("seller", User.Role.SELLER)
        self.other_seller = self.make_user("seller2", User.Role.SELLER)
        self.buyer = self.make_user("buyer", User.Role.BUYER)
        self.pickup = DeliveryOption.objects.get(kind=DeliveryOption.Kind.PICKUP)
        self.courier = DeliveryOption.objects.create(
            name="Accra courier", kind=DeliveryOption.Kind.COURIER, fee=Decimal("25.00"), regions="Greater Accra",
        )
        self.phone = self.make_product("Phone", self.seller, price="1000.00", stock=3)
        self.shoes = self.make_product("Shoes", self.other_seller, price="200.00", stock=5, category="fashion")

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, email=f"{username}@example.com", password=PASSWORD, role=role,
            phone_number="0240000000", city="Accra", region=GhanaRegion.GREATER_ACCRA,
        )

    def make_product(self, title, seller, price="10.00", stock=1, category="phones-tech", checkout=True):
        return Product.objects.create(
            seller=seller, title=title, description="Test item.", category_id=category, price=price,
            city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED,
            allows_checkout=checkout, stock_quantity=stock,
        )

    def address(self, region=GhanaRegion.GREATER_ACCRA):
        return Address.objects.create(
            user=self.buyer, full_name="Ama Mensah", phone_number="0241111111", region=region,
            city="Accra", street="12 Oxford Street",
        )

    def place_order(self, quantity=1):
        services.add_to_cart(self.buyer, self.phone, quantity)
        return services.create_checkout(self.buyer, {self.seller.pk: self.pickup})


class CartTests(CommerceFixtures):
    def test_cannot_buy_own_listing(self):
        with self.assertRaisesMessage(services.CommerceError, "own listing"):
            services.add_to_cart(self.seller, self.phone)

    def test_contact_only_listing_cannot_be_added(self):
        product = self.make_product("Contact only", self.seller, checkout=False)
        with self.assertRaises(services.CommerceError):
            services.add_to_cart(self.buyer, product)

    def test_category_without_checkout_blocks_cart(self):
        car = self.make_product("Car", self.seller, category="vehicles")
        self.assertFalse(car.can_checkout)
        with self.assertRaises(services.CommerceError):
            services.add_to_cart(self.buyer, car)

    def test_quantity_is_limited_by_stock(self):
        services.add_to_cart(self.buyer, self.phone, 3)
        with self.assertRaisesMessage(services.CommerceError, "Only 3 available"):
            services.add_to_cart(self.buyer, self.phone, 1)

    def test_cart_page_and_add_view(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("commerce:cart_add", args=[self.phone.pk]), {"quantity": 2})
        self.assertRedirects(response, reverse("commerce:cart"))
        page = self.client.get(reverse("commerce:cart"))
        self.assertContains(page, "Phone")
        self.assertContains(page, "GH₵ 2,000")

    def test_users_cannot_change_other_peoples_cart_items(self):
        item = services.add_to_cart(self.buyer, self.phone)
        self.client.force_login(self.other_seller)
        response = self.client.post(reverse("commerce:cart_update", args=[item.pk]), {"quantity": 3})
        self.assertEqual(response.status_code, 404)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)


class CheckoutTests(CommerceFixtures):
    def test_checkout_splits_orders_per_seller_and_reserves_stock(self):
        services.add_to_cart(self.buyer, self.phone, 2)
        services.add_to_cart(self.buyer, self.shoes, 1)
        address = self.address()

        checkout = services.create_checkout(
            self.buyer, {self.seller.pk: self.courier, self.other_seller.pk: self.pickup}, address=address,
        )

        self.assertEqual(checkout.orders.count(), 2)
        self.assertEqual(checkout.total, Decimal("2000.00") + Decimal("25.00") + Decimal("200.00"))
        phone_order = checkout.orders.get(seller=self.seller)
        self.assertEqual(phone_order.delivery_address, address.as_text())
        self.assertEqual(phone_order.status, Order.Status.PENDING_PAYMENT)
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.stock_quantity, 1)
        self.assertFalse(CartItem.objects.filter(user=self.buyer).exists())

    def test_stock_is_rechecked_at_checkout(self):
        services.add_to_cart(self.buyer, self.phone, 3)
        Product.objects.filter(pk=self.phone.pk).update(stock_quantity=1)
        with self.assertRaisesMessage(services.CommerceError, "Only 1"):
            services.create_checkout(self.buyer, {self.seller.pk: self.pickup})
        self.assertFalse(Checkout.objects.exists())

    def test_delivery_requires_address_and_served_region(self):
        services.add_to_cart(self.buyer, self.phone)
        with self.assertRaisesMessage(services.CommerceError, "address"):
            services.create_checkout(self.buyer, {self.seller.pk: self.courier})
        with self.assertRaisesMessage(services.CommerceError, "does not deliver"):
            services.create_checkout(self.buyer, {self.seller.pk: self.courier}, address=self.address(GhanaRegion.VOLTA))

    def test_checkout_view_with_new_address(self):
        services.add_to_cart(self.buyer, self.phone)
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("commerce:checkout"), {
            f"delivery_{self.seller.pk}": self.courier.pk, "new-full_name": "Ama Mensah",
            "new-phone_number": "0241111111", "new-region": GhanaRegion.GREATER_ACCRA, "new-city": "Accra",
            "new-street": "Ring Road",
        })
        checkout = Checkout.objects.get()
        self.assertRedirects(response, reverse("commerce:checkout_pay", args=[checkout.reference]))
        self.assertEqual(Address.objects.get().street, "Ring Road")

    def test_cancelling_unpaid_checkout_returns_stock(self):
        checkout = self.place_order(2)
        self.client.force_login(self.buyer)
        self.client.post(reverse("commerce:checkout_cancel", args=[checkout.reference]))
        checkout.refresh_from_db()
        self.phone.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.CANCELLED)
        self.assertEqual(self.phone.stock_quantity, 3)
        self.assertEqual(checkout.orders.get().status, Order.Status.CANCELLED)

    def test_expiry_returns_stock(self):
        checkout = self.place_order()
        Checkout.objects.filter(pk=checkout.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.expire_stale_checkouts(), 1)
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.stock_quantity, 3)

    def test_other_buyers_cannot_see_a_checkout(self):
        checkout = self.place_order()
        self.client.force_login(self.other_seller)
        self.assertEqual(self.client.get(reverse("commerce:checkout_pay", args=[checkout.reference])).status_code, 404)

    @override_settings(PAYMENT_PROVIDER="")
    def test_checkout_is_disabled_without_a_payment_provider(self):
        services.add_to_cart(self.buyer, self.phone)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("commerce:checkout"), follow=True)
        self.assertRedirects(response, reverse("commerce:cart"))
        self.assertContains(response, "Online payment is not available yet")


class PaymentConfirmationTests(CommerceFixtures):
    def start(self, checkout):
        return services.start_payment(checkout, TestProvider(), "http://testserver/payments/callback/") and \
            checkout.payments.get()

    def test_successful_verified_payment_marks_orders_paid_and_notifies(self):
        checkout = self.place_order()
        payment = self.start(checkout)
        services.apply_verification(payment, VerificationResult(
            status="success", amount=payment.amount, currency="GHS", channel="mobile_money", transaction_id="9",
        ))
        checkout.refresh_from_db()
        order = checkout.orders.get()
        self.assertEqual(checkout.status, Checkout.Status.PAID)
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNotNone(order.paid_at)
        self.assertTrue(Notification.objects.filter(user=self.seller, title__contains=order.number).exists())

    def test_duplicate_confirmation_is_ignored(self):
        checkout = self.place_order()
        payment = self.start(checkout)
        result = VerificationResult(status="success", amount=payment.amount, currency="GHS")
        services.apply_verification(payment, result)
        services.apply_verification(payment, result)
        self.assertEqual(checkout.orders.get().events.filter(to_status=Order.Status.PAID).count(), 1)

    def test_amount_mismatch_is_rejected(self):
        checkout = self.place_order()
        payment = self.start(checkout)
        services.apply_verification(payment, VerificationResult(status="success", amount=Decimal("1.00"), currency="GHS"))
        payment.refresh_from_db()
        checkout.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertIn("mismatch", payment.failure_reason)
        self.assertEqual(checkout.status, Checkout.Status.PENDING)

    def test_callback_without_provider_confirmation_does_not_mark_paid(self):
        checkout = self.place_order()
        payment = self.start(checkout)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("commerce:payment_callback"), {"reference": payment.reference}, follow=True)
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.PENDING)
        self.assertContains(response, "still waiting")

    def test_payment_after_expiry_is_flagged_for_refund_not_applied(self):
        checkout = self.place_order()
        payment = self.start(checkout)
        services.close_unpaid_checkout(checkout, status=Checkout.Status.EXPIRED)
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))
        payment.refresh_from_db()
        checkout.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertIn("refund required", payment.failure_reason)
        self.assertEqual(checkout.status, Checkout.Status.EXPIRED)

    def test_full_test_provider_flow_through_views(self):
        checkout = self.place_order()
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("commerce:checkout_pay", args=[checkout.reference]))
        payment = checkout.payments.get()
        self.assertRedirects(response, reverse("commerce:test_payment", args=[payment.reference]))
        response = self.client.post(reverse("commerce:test_payment", args=[payment.reference]), {"outcome": "success"},
                                    follow=True)
        self.assertContains(response, "Payment confirmed")
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.PAID)

    @override_settings(DEBUG=False)
    def test_test_provider_refuses_to_run_without_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            get_provider("test")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fake_opener(responses, calls):
    def opener(request, timeout):
        calls.append(request)
        return FakeResponse(json.dumps(responses.pop(0)).encode())
    return opener


@override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY=SECRET)
class PaystackTests(CommerceFixtures):
    def test_initialize_sends_pesewas_and_returns_hosted_page(self):
        checkout = self.place_order()
        calls = []
        provider = PaystackProvider(SECRET, opener=fake_opener(
            [{"status": True, "data": {"authorization_url": "https://checkout.paystack.com/abc"}}], calls))
        url = services.start_payment(checkout, provider, "https://example.com/cb")
        body = json.loads(calls[0].data)
        self.assertEqual(url, "https://checkout.paystack.com/abc")
        self.assertEqual(body["amount"], "100000")
        self.assertEqual(body["currency"], "GHS")
        self.assertEqual(calls[0].get_header("Authorization"), f"Bearer {SECRET}")

    def test_verify_maps_paystack_success(self):
        checkout = self.place_order()
        payment = Payment.objects.create(checkout=checkout, provider="paystack", reference="R1", amount=checkout.total,
                                         currency="GHS")
        provider = PaystackProvider(SECRET, opener=fake_opener([{"status": True, "data": {
            "status": "success", "amount": 100000, "currency": "GHS", "channel": "mobile_money", "id": 55,
            "authorization": {"last4": "4081"},
        }}], []))
        result = provider.verify(payment)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.amount, Decimal("1000.00"))
        self.assertNotIn("authorization", result.raw)

    def signed_post(self, payload):
        body = json.dumps(payload).encode()
        signature = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
        return self.client.post(reverse("commerce:payment_webhook", args=["paystack"]), body,
                                content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature)

    def test_webhook_rejects_bad_signature(self):
        response = self.client.post(reverse("commerce:payment_webhook", args=["paystack"]), b"{}",
                                    content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE="nope")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentEvent.objects.exists())

    def test_webhook_reverifies_and_ignores_duplicates(self):
        checkout = self.place_order()
        payment = Payment.objects.create(checkout=checkout, provider="paystack", reference="R2", amount=checkout.total,
                                         currency="GHS")
        verified = VerificationResult(status="success", amount=checkout.total, currency="GHS", channel="card")
        payload = {"event": "charge.success", "data": {"reference": "R2", "amount": 100000}}
        with mock.patch.object(PaystackProvider, "verify", return_value=verified) as verify:
            first = self.signed_post(payload)
            second = self.signed_post(payload)
        self.assertEqual(first.content, b"ok")
        self.assertEqual(second.content, b"duplicate")
        self.assertEqual(verify.call_count, 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(PaymentEvent.objects.get().outcome, "Payment succeeded")


class OrderLifecycleTests(CommerceFixtures):
    def paid_order(self, quantity=1):
        checkout = self.place_order(quantity)
        payment = services.start_payment(checkout, TestProvider(), "http://testserver/cb") and checkout.payments.get()
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))
        return checkout.orders.get()

    def test_seller_moves_order_forward_and_buyer_completes(self):
        order = self.paid_order()
        services.change_order_status(order, Order.Status.PROCESSING, self.seller)
        services.change_order_status(order, Order.Status.READY_FOR_PICKUP, self.seller, note="Meet at Accra Mall")
        services.change_order_status(order, Order.Status.COMPLETED, self.buyer)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)
        self.assertEqual(order.events.count(), 5)

    def test_buyer_cannot_mark_order_shipped(self):
        order = self.paid_order()
        with self.assertRaises(services.CommerceError):
            services.change_order_status(order, Order.Status.SHIPPED, self.buyer)

    def test_unpaid_orders_cannot_be_progressed(self):
        order = self.place_order().orders.get()
        with self.assertRaises(services.CommerceError):
            services.change_order_status(order, Order.Status.PROCESSING, self.seller)

    def test_seller_cancellation_refunds_and_restocks(self):
        order = self.paid_order(2)
        with self.assertRaisesMessage(services.CommerceError, "reason"):
            services.change_order_status(order, Order.Status.CANCELLED, self.seller)
        services.change_order_status(order, Order.Status.CANCELLED, self.seller, note="Out of stock")
        order.refresh_from_db()
        self.phone.refresh_from_db()
        refund = Refund.objects.get()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(refund.amount, order.total)
        self.assertEqual(refund.status, Refund.Status.COMPLETED)
        self.assertEqual(self.phone.stock_quantity, 3)

    def test_refund_cannot_exceed_order_total(self):
        order = self.paid_order()
        services.refund_order(order, Decimal("400.00"), None, "Partial")
        with self.assertRaises(services.CommerceError):
            services.refund_order(order, Decimal("700.00"), None, "Too much")

    def test_seller_order_pages_are_private(self):
        order = self.paid_order()
        self.client.force_login(self.other_seller)
        self.assertEqual(self.client.get(reverse("commerce:seller_order_detail", args=[order.number])).status_code, 404)
        self.client.force_login(self.seller)
        page = self.client.get(reverse("commerce:seller_order_detail", args=[order.number]))
        self.assertContains(page, "Save and notify buyer")
        self.assertNotContains(self.client.get(reverse("commerce:order_list")), order.number)

    def test_seller_status_form_updates_order(self):
        order = self.paid_order()
        self.client.force_login(self.seller)
        self.client.post(reverse("commerce:seller_order_detail", args=[order.number]), {
            "to_status": Order.Status.PROCESSING, "note": "Packing now",
        })
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PROCESSING)
        self.assertTrue(Notification.objects.filter(user=self.buyer, title__contains="Being prepared").exists())

    def test_buyer_can_open_one_issue_per_order(self):
        order = self.paid_order()
        self.client.force_login(self.buyer)
        url = reverse("commerce:order_issue", args=[order.number])
        self.client.post(url, {"kind": OrderIssue.Kind.REFUND, "reason": "Damaged screen"})
        self.client.post(url, {"kind": OrderIssue.Kind.REFUND, "reason": "Again"})
        self.assertEqual(OrderIssue.objects.count(), 1)
        self.client.force_login(self.other_seller)
        self.assertEqual(self.client.post(url, {"kind": "dispute", "reason": "x"}).status_code, 404)

    def test_seller_orders_list_excludes_unpaid(self):
        unpaid = self.place_order().orders.get()
        self.client.force_login(self.seller)
        self.assertNotContains(self.client.get(reverse("commerce:seller_orders")), unpaid.number)


class ListingSellingMethodTests(CommerceFixtures):
    def test_detail_page_shows_buy_box_only_for_checkout_listings(self):
        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse("product_detail", args=[self.phone.pk])), "Buy now")
        contact_only = self.make_product("Fridge", self.seller, checkout=False)
        self.assertNotContains(self.client.get(reverse("product_detail", args=[contact_only.pk])), "Buy now")

    def test_checkout_only_listing_blocks_messages(self):
        Product.objects.filter(pk=self.phone.pk).update(allows_direct_contact=False)
        self.client.force_login(self.buyer)
        self.client.post(reverse("conversation_start", args=[self.phone.pk]), {"body": "Hi"})
        self.assertFalse(self.phone.conversations.exists())
