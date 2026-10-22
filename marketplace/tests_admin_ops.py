from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from commerce import services
from commerce.models import DeliveryOption
from commerce.payments import VerificationResult
from commerce.payments.test_provider import TestProvider

from .models import GhanaRegion, Product, SupportRequest, User, UserReport

PASSWORD = "A-strong-password-482!"


@override_settings(DEBUG=True, PAYMENT_PROVIDER="test")
class AdminOperationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.staff = User.objects.create_user("helper", "helper@example.com", PASSWORD, is_staff=True)
        self.seller = User.objects.create_user("seller", "seller@example.com", PASSWORD, role=User.Role.SELLER)
        self.buyer = User.objects.create_user("buyer", "buyer@example.com", PASSWORD)
        self.product = Product.objects.create(
            seller=self.seller, title="Blender", description="x", category_id="home-living", price="250.00",
            city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED,
            allows_checkout=True, stock_quantity=3,
        )

    def pay_for(self, quantity):
        services.add_to_cart(self.buyer, self.product, quantity)
        checkout = services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))

    def test_dashboard_shows_real_queue_counts_and_sales(self):
        UserReport.objects.create(reporter=self.buyer, reported=self.seller, reason=UserReport.Reason.SCAM)
        SupportRequest.objects.create(email="a@example.com", topic="appeal", subject="Appeal", message="Please")
        self.pay_for(2)
        services.add_to_cart(self.buyer, self.product, 1)
        services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})  # unpaid

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))

        queues = {q["label"]: q["count"] for q in response.context["admin_dashboard_queues"]}
        self.assertEqual(queues["User reports"], 1)
        self.assertEqual(queues["Support requests"], 1)
        commerce = response.context["admin_dashboard_commerce"]
        self.assertEqual(commerce["paid_orders"], 1)  # the unpaid checkout is not counted
        self.assertEqual(commerce["paid_value"], 500)
        self.assertEqual(commerce["awaiting_seller"], 1)

    def test_staff_only_see_queues_they_have_permission_for(self):
        self.staff.user_permissions.add(Permission.objects.get(codename="view_supportrequest"))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual([q["label"] for q in response.context["admin_dashboard_queues"]], ["Support requests"])
        self.assertNotIn("admin_dashboard_commerce", response.context)

    def test_analytics_reports_verified_sales_only(self):
        self.pay_for(1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("marketplace_admin_analytics"), {"period": 7})
        self.assertEqual(response.context["order_paid_count"], 1)
        self.assertEqual(response.context["order_paid_value"], 250)
        self.assertEqual(response.context["payment_success_rate"], 100)
        self.assertContains(response, "Payments and orders")

    def test_order_admin_is_read_only_and_refund_needs_permission(self):
        self.pay_for(1)
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=("view_order", "change_order")))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:commerce_order_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "refund_in_full")
        self.staff.user_permissions.add(Permission.objects.get(codename="add_refund"))
        self.assertContains(self.client.get(reverse("admin:commerce_order_changelist")), "refund_in_full")
