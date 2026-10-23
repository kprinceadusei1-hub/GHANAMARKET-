"""Regression tests for the final commerce audit fixes."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from marketplace.models import Notification, User, UserBlock

from . import services
from .models import Checkout, Order, Payment, PaymentEvent, Refund
from .payments import PaymentError, VerificationResult
from .payments.paystack import PaystackProvider
from .payments.test_provider import TestProvider
from .tests import SECRET, CommerceFixtures, fake_opener


def succeed(payment):
    return services.apply_verification(payment, VerificationResult(
        status="success", amount=payment.amount, currency="GHS", channel="mobile_money", transaction_id=str(payment.pk)))


class DuplicateAndLatePaymentTests(CommerceFixtures):
    def test_double_payment_is_flagged_refundable_and_buyer_told(self):
        checkout = self.place_order()
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        first, second = checkout.payments.order_by("created_at")
        succeed(first)
        second = succeed(second)
        self.assertIn("refund required", second.failure_reason)
        self.assertTrue(Notification.objects.filter(user=self.buyer, title="We received an extra payment").exists())
        self.assertTrue(services.needs_payment_refund(second))
        refund = services.refund_payment(second, self.seller, provider=TestProvider())
        self.assertEqual(refund.status, Refund.Status.COMPLETED)
        self.assertIsNone(refund.order)
        self.assertEqual(refund.amount, second.amount)
        self.assertFalse(services.needs_payment_refund(second))
        # An order refund still goes against the payment that actually paid for it.
        order = checkout.orders.get()
        order_refund = services.refund_order(order, Decimal("100.00"), self.seller, "Partial", provider=TestProvider())
        self.assertEqual(order_refund.payment, first)

    def test_late_payment_after_expiry_can_be_refunded(self):
        checkout = self.place_order()
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        services.close_unpaid_checkout(checkout, status=Checkout.Status.EXPIRED)
        payment = succeed(payment)
        self.assertTrue(services.needs_payment_refund(payment))
        self.assertEqual(services.refund_payment(payment, None, provider=TestProvider()).status,
                         Refund.Status.COMPLETED)


class ExpiryGraceTests(CommerceFixtures):
    def test_payment_in_progress_is_checked_before_expiry(self):
        checkout = self.place_order()
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        payment.provider_response = {**payment.provider_response, "test_outcome": "success"}
        payment.save()
        Checkout.objects.filter(pk=checkout.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.expire_stale_checkouts(), 0)
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.PAID)

    def test_pending_payment_gets_grace_then_expires(self):
        checkout = self.place_order()
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        Checkout.objects.filter(pk=checkout.pk).update(expires_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(services.expire_stale_checkouts(), 0)
        later = timezone.now() + timedelta(minutes=services.PAYMENT_GRACE_MINUTES + 1)
        self.assertEqual(services.expire_stale_checkouts(now=later), 1)
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.EXPIRED)

    def test_checkout_without_payment_expires_on_time(self):
        checkout = self.place_order()
        Checkout.objects.filter(pk=checkout.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.expire_stale_checkouts(), 1)


@override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY=SECRET)
class WebhookOutageTests(CommerceFixtures):
    def test_provider_outage_is_retried_not_lost(self):
        import hashlib
        import hmac
        import json

        checkout = self.place_order()
        Payment.objects.create(checkout=checkout, provider="paystack", reference="R9", amount=checkout.total,
                               currency="GHS")
        body = json.dumps({"event": "charge.success", "data": {"reference": "R9"}}).encode()
        signature = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()

        def post():
            return self.client.post(reverse("commerce:payment_webhook", args=["paystack"]), body,
                                    content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature)

        with mock.patch.object(PaystackProvider, "verify", side_effect=PaymentError("timeout")):
            first = post()
        self.assertEqual(first.status_code, 503)
        self.assertIsNone(PaymentEvent.objects.get().processed_at)
        verified = VerificationResult(status="success", amount=checkout.total, currency="GHS", channel="card")
        with mock.patch.object(PaystackProvider, "verify", return_value=verified):
            retry = post()
        self.assertEqual(retry.content, b"ok")
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, Checkout.Status.PAID)

    def test_refund_status_is_rechecked(self):
        checkout = self.place_order()
        payment = Payment.objects.create(checkout=checkout, provider="paystack", reference="R10",
                                         amount=checkout.total, currency="GHS", status=Payment.Status.SUCCEEDED)
        Checkout.objects.filter(pk=checkout.pk).update(status=Checkout.Status.PAID)
        order = checkout.orders.get()
        Order.objects.filter(pk=order.pk).update(paid_at=timezone.now(), status=Order.Status.PAID)
        refund = Refund.objects.create(order=order, payment=payment, amount=Decimal("10"), reason="x",
                                       provider_reference="77", status=Refund.Status.REQUESTED)
        provider = PaystackProvider(SECRET, opener=fake_opener([{"status": True, "data": {"status": "failed"}}], []))
        services.recheck_refund(refund, provider=provider)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.FAILED)


class SellerVisibilityAndBlockingTests(CommerceFixtures):
    def test_seller_never_sees_unpaid_orders_or_buyer_details(self):
        checkout = self.place_order()
        services.close_unpaid_checkout(checkout)
        order = checkout.orders.get()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.client.force_login(self.seller)
        self.assertNotContains(self.client.get(reverse("commerce:seller_orders")), order.number)
        self.assertEqual(self.client.get(reverse("commerce:seller_order_detail", args=[order.number])).status_code, 404)

    def test_blocked_buyer_cannot_add_or_check_out(self):
        UserBlock.objects.create(blocker=self.seller, blocked=self.buyer)
        with self.assertRaises(services.CommerceError):
            services.add_to_cart(self.buyer, self.phone, 1)

    def test_block_after_adding_to_cart_stops_checkout(self):
        services.add_to_cart(self.buyer, self.phone, 1)
        UserBlock.objects.create(blocker=self.seller, blocked=self.buyer)
        with self.assertRaises(services.CommerceError):
            services.create_checkout(self.buyer, {self.seller.pk: self.pickup})


class CancelAfterPartialRefundTests(CommerceFixtures):
    def test_seller_can_cancel_after_a_partial_refund(self):
        checkout = self.place_order()
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        succeed(checkout.payments.get())
        order = checkout.orders.get()
        services.refund_order(order, Decimal("100.00"), self.seller, "Partial", provider=TestProvider())
        with mock.patch("commerce.payments.get_provider", return_value=TestProvider()):
            services.change_order_status(order, Order.Status.CANCELLED, self.seller, "Out of stock")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(services.refunded_amount(order), order.total)


class StockEditTests(CommerceFixtures):
    def test_seller_edit_keeps_units_reserved_by_buyers(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "green").save(buffer, format="JPEG")
        self.phone.image = SimpleUploadedFile("phone.jpg", buffer.getvalue(), content_type="image/jpeg")
        self.phone.save()
        self.client.force_login(self.seller)
        url = reverse("product_update", args=[self.phone.pk])
        form = self.client.get(url).context["form"]
        self.assertEqual(form["stock_seen"].value(), 3)
        services.add_to_cart(self.buyer, self.phone, 2)
        services.create_checkout(self.buyer, {self.seller.pk: self.pickup})  # reserves 2 → 1 left
        data = {
            "title": self.phone.title, "description": self.phone.description, "category": "phones-tech",
            "price": "1000.00", "condition": self.phone.condition, "region": self.phone.region,
            "city": self.phone.city, "allows_checkout": "on", "allows_direct_contact": "on",
            "stock_quantity": "4", "stock_seen": "3",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.phone.refresh_from_db()
        # The seller added 1 unit (3 → 4); the 2 reserved units stay reserved: 1 + 1 = 2 available.
        self.assertEqual(self.phone.stock_quantity, 2)
