from datetime import timedelta

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from commerce import services
from commerce.models import DeliveryOption
from commerce.payments import VerificationResult
from commerce.payments.test_provider import TestProvider

from .models import GhanaRegion, ListingReport, Product, SellerVerification, SupportRequest, User

PASSWORD = "A-strong-password-482!"


@override_settings(DEBUG=True, PAYMENT_PROVIDER="test")
class ControlCentreTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD, first_name="Efua")
        self.seller = User.objects.create_user("seller", "seller@example.com", PASSWORD, role=User.Role.SELLER,
                                               first_name="Kofi", last_name="Boateng")
        self.buyer = User.objects.create_user("buyer", "buyer@example.com", PASSWORD, first_name="Ama",
                                              last_name="Serwaa", phone_number="0241112222")
        self.live = Product.objects.create(
            seller=self.seller, title="Blender", description="x", category_id="home-living", price="250.00",
            city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED,
            allows_checkout=True, stock_quantity=5,
        )

    def pay(self, quantity=1):
        services.add_to_cart(self.buyer, self.live, quantity)
        checkout = services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})
        services.start_payment(checkout, TestProvider(), "http://testserver/cb")
        payment = checkout.payments.get()
        services.apply_verification(payment, VerificationResult(status="success", amount=payment.amount, currency="GHS"))
        return checkout.orders.get()

    def dashboard(self, user=None, **params):
        self.client.force_login(user or self.admin)
        return self.client.get(reverse("admin:index"), params)

    def test_kpis_use_real_data_and_exclude_previews(self):
        Product.objects.create(seller=self.seller, title="Preview", description="x", category_id="fashion",
                               price="9", city="Accra", status=Product.Status.PUBLISHED, is_demo=True)
        self.pay(2)
        kpis = {k["label"]: k for k in self.dashboard().context["cc_kpis"]}
        self.assertEqual(kpis["Active listings"]["value"], 1)
        self.assertEqual(kpis["Active sellers"]["value"], 1)
        self.assertEqual(kpis["Paid orders"]["value"], 1)
        self.assertEqual(kpis["Paid order value"]["value"], 500)
        self.assertEqual(kpis["Total users"]["value"], 3)

    def test_unpaid_orders_never_count_as_sales(self):
        services.add_to_cart(self.buyer, self.live, 1)
        services.create_checkout(self.buyer, {self.seller.pk: DeliveryOption.objects.get(kind="pickup")})
        response = self.dashboard()
        kpis = {k["label"]: k for k in response.context["cc_kpis"]}
        self.assertEqual(kpis["Paid orders"]["value"], 0)
        self.assertIsNone(response.context["cc_sales"])
        self.assertContains(response, "No paid orders in the last 7 days")

    def test_sales_chart_and_category_donut(self):
        self.pay()
        response = self.dashboard(period=30)
        chart = response.context["cc_sales"]
        self.assertEqual(chart["total_orders"], 1)
        self.assertEqual(len(chart["points"]), 30)
        donut = response.context["cc_categories"]
        self.assertEqual(donut["total"], 1)
        self.assertEqual(donut["segments"][0]["label"], "Home & Living")

    def test_period_filter_validates_input(self):
        self.assertEqual(self.dashboard(period=90).context["cc_period"], 90)
        self.assertEqual(self.dashboard(period=365).context["cc_period"], 7)

    def test_change_is_against_previous_period(self):
        User.objects.filter(pk=self.buyer.pk).update(date_joined=timezone.now() - timedelta(days=10))
        kpis = {k["label"]: k for k in self.dashboard().context["cc_kpis"]}
        # Two users joined this week (admin, seller) and one the week before (buyer): +100%.
        self.assertEqual(kpis["Total users"]["change"], 100)

    def test_quick_stats_and_approvals_queue(self):
        Product.objects.create(seller=self.seller, title="Pending phone", description="x", category_id="phones-tech",
                               price="10", city="Accra", status=Product.Status.PENDING)
        SellerVerification.objects.create(user=self.seller, kind="ghana_card", legal_name="Kofi Boateng",
                                          document_number="GHA-1", document="verifications/x.pdf")
        ListingReport.objects.create(product=self.live, reporter=self.buyer, reason="scam")
        SupportRequest.objects.create(email="a@example.com", topic="appeal", subject="Help", message="Please")
        response = self.dashboard()
        stats = {s["key"]: s["count"] for s in response.context["cc_quick_stats"]}
        self.assertEqual(stats["verifications"], 1)
        self.assertEqual(stats["listing_reports"], 1)
        self.assertEqual(stats["support"], 1)
        self.assertEqual(stats["pending_listings"], 1)
        self.assertEqual({item["action"] for item in response.context["cc_approvals"]}, {"Verify", "Review"})
        self.assertEqual(response.context["cc_alert_total"], 4)

    def test_recent_orders_hide_contact_details(self):
        order = self.pay()
        response = self.dashboard()
        self.assertContains(response, order.number)
        self.assertContains(response, "Ama S.")
        self.assertNotContains(response, "0241112222")
        self.assertNotContains(response, "buyer@example.com")

    def test_activity_feed_includes_audit_log(self):
        LogEntry.objects.log_action(self.admin.pk, ContentType.objects.get_for_model(Product).pk, self.live.pk,
                                    "Blender", CHANGE, "Approved")
        titles = [event["title"] for event in self.dashboard().context["cc_activity"]]
        self.assertIn("Changed product", titles)

    def test_limited_staff_only_see_permitted_sections(self):
        staff = User.objects.create_user("helper", "helper@example.com", PASSWORD, is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_supportrequest"))
        response = self.dashboard(user=staff)
        self.assertEqual(response.context["cc_kpis"], [])
        self.assertIsNone(response.context["cc_recent_orders"])
        self.assertFalse(response.context["cc_can_sales"])
        self.assertEqual([q["key"] for q in response.context["cc_quick_stats"]], ["support"])
        self.assertEqual([g["label"] for g in response.context["cc_sidebar"]], ["Support & Tickets"])
        self.assertNotContains(response, "Paid order value")

    def test_global_search_respects_permissions(self):
        order = self.pay()
        self.client.force_login(self.admin)
        url = reverse("marketplace_admin_search")
        groups = dict(self.client.get(url, {"q": "Blender"}).context["groups"])
        self.assertEqual(groups["Listings"][0]["title"], "Blender")
        self.assertEqual(self.client.get(url, {"q": order.number}).context["result_total"], 1)
        by_id = dict(self.client.get(url, {"q": f"#{self.live.pk}"}).context["groups"])
        self.assertEqual(by_id["Listings"][0]["title"], "Blender")

        staff = User.objects.create_user("helper", "helper@example.com", PASSWORD, is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url, {"q": "Blender"}).status_code, 403)

    def test_non_staff_cannot_open_control_centre(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.assertEqual(self.client.get(reverse("marketplace_admin_search"), {"q": "x"}).status_code, 302)


class PreviewRemovalTests(TestCase):
    def setUp(self):
        from django.core.management import call_command

        call_command("seed_demo_marketplace", verbosity=0)
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        seller = User.objects.create_user("real", "real@example.com", PASSWORD, role=User.Role.SELLER)
        self.real = Product.objects.create(seller=seller, title="Real chair", description="x", category_id="home-living",
                                           price="50", city="Accra", status=Product.Status.PUBLISHED)
        self.url = reverse("marketplace_delete_previews")

    def test_banner_explains_previews_and_offers_removal(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "next to real ads")
        self.assertContains(response, "Remove all previews")
        self.assertNotContains(response, "until the first real ad is approved")

    def test_superuser_removes_previews_and_keeps_real_ads(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "Only real ads are shown now")
        self.assertFalse(Product.objects.filter(is_demo=True).exists())
        self.assertTrue(Product.objects.filter(pk=self.real.pk).exists())
        self.assertTrue(LogEntry.objects.filter(change_message__contains="preview catalogue").exists())
        self.assertNotContains(self.client.get(reverse("admin:index")), "Remove all previews")

    def test_only_superusers_by_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        staff = User.objects.create_user("helper", "h@example.com", PASSWORD, is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=("view_product", "delete_product")))
        self.client.force_login(staff)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:index")), "Remove all previews")
        self.assertTrue(Product.objects.filter(is_demo=True).exists())
