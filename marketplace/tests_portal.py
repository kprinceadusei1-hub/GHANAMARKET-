"""Buyer/seller portal additions: view counts, mark as sold, account overview, storefronts,
password change, homepage banners and staff roles."""
import io
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import trust
from .models import Conversation, GhanaRegion, HomeBanner, Product, User
from .staff_roles import ROLES, setup_staff_roles
from .tests_images import photo_with_gps

PASSWORD = "A-strong-password-482!"


def png_bytes(size=(200, 200)):
    buffer = io.BytesIO()
    Image.new("RGBA", size, (10, 120, 60, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class PortalBase(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER,
                                               first_name="Selina", phone_number="0241112222",
                                               city="Accra", region=GhanaRegion.GREATER_ACCRA)
        self.other_seller = User.objects.create_user("other", "o@example.com", PASSWORD, role=User.Role.SELLER)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD, first_name="Ama")
        self.product = self.make_product(self.seller, "Dress")

    def make_product(self, seller, title, status=Product.Status.PUBLISHED, **extra):
        return Product.objects.create(seller=seller, title=title, description="x", category_id="fashion",
                                      price="240", city="Accra", region=GhanaRegion.GREATER_ACCRA,
                                      status=status, **extra)


class ViewCountTests(PortalBase):
    def test_counts_once_per_visitor_session(self):
        url = reverse("product_detail", args=[self.product.pk])
        self.client.get(url)
        self.client.get(url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 1)
        self.client.logout()
        self.client.cookies.clear()
        self.client.force_login(self.buyer)
        self.client.get(url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.view_count, 2)

    def test_seller_own_views_and_preview_listings_do_not_count(self):
        self.client.force_login(self.seller)
        self.client.get(reverse("product_detail", args=[self.product.pk]))
        demo = self.make_product(self.other_seller, "Preview", is_demo=True)
        self.client.get(reverse("product_detail", args=[demo.pk]))
        self.product.refresh_from_db()
        demo.refresh_from_db()
        self.assertEqual((self.product.view_count, demo.view_count), (0, 0))

    def test_counting_does_not_bump_updated_at(self):
        before = self.product.updated_at
        self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.updated_at, before)


class MarkSoldTests(PortalBase):
    def post(self, product, action):
        return self.client.post(reverse("seller_listing_status", args=[product.pk]), {"action": action}, follow=True)

    def test_owner_marks_sold_and_relists_through_review(self):
        self.client.force_login(self.seller)
        self.assertContains(self.post(self.product, "mark_sold"), "marked as sold")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SOLD)
        self.assertEqual(self.client.get(reverse("product_detail", args=[self.product.pk])).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("product_detail", args=[self.product.pk])).status_code, 404)
        self.client.force_login(self.seller)
        self.post(self.product, "relist")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_only_published_listings_can_be_marked_sold(self):
        pending = self.make_product(self.seller, "Waiting", status=Product.Status.PENDING)
        self.client.force_login(self.seller)
        self.assertContains(self.post(pending, "mark_sold"), "not available")
        pending.refresh_from_db()
        self.assertEqual(pending.status, Product.Status.PENDING)

    def test_other_sellers_cannot_change_the_listing(self):
        self.client.force_login(self.other_seller)
        response = self.client.post(reverse("seller_listing_status", args=[self.product.pk]), {"action": "mark_sold"})
        self.assertEqual(response.status_code, 404)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)


class AccountOverviewTests(PortalBase):
    def test_requires_login(self):
        response = self.client.get(reverse("account_overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_buyer_sees_buyer_sections_only(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("account_overview"))
        self.assertContains(response, "My orders")
        self.assertContains(response, "Start selling")
        self.assertNotContains(response, "Your shop")

    def test_seller_figures_are_their_own(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=7)
        self.make_product(self.seller, "Old phone", status=Product.Status.SOLD, view_count=3)
        self.make_product(self.other_seller, "Not mine", view_count=500)
        Conversation.objects.create(product=self.product, buyer=self.buyer, seller=self.seller)
        self.client.force_login(self.seller)
        response = self.client.get(reverse("account_overview"))
        figures = response.context["seller"]
        self.assertEqual((figures["live"], figures["sold"], figures["views"], figures["enquiries"]), (1, 1, 10, 1))
        self.assertEqual(figures["sales_30d"], 0)
        self.assertContains(response, "Finish your storefront")

    def test_seller_dashboard_shows_views_and_enquiries(self):
        Product.objects.filter(pk=self.product.pk).update(view_count=12)
        self.client.force_login(self.seller)
        response = self.client.get(reverse("seller_listings"))
        self.assertContains(response, "12 views")
        self.assertContains(response, "Mark as sold")


class StorefrontTests(PortalBase):
    def test_buyers_are_sent_away(self):
        self.client.force_login(self.buyer)
        self.assertRedirects(self.client.get(reverse("storefront_settings")), reverse("account_overview"))

    def test_seller_saves_name_logo_and_description(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("storefront_settings"), {
            "store_name": "  Selina's   Fashion ", "store_description": "Ladies wear in Osu.",
            "store_logo": SimpleUploadedFile("logo.jpg", photo_with_gps((800, 800)), content_type="image/jpeg"),
        })
        self.assertRedirects(response, reverse("storefront_settings"))
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.store_name, "Selina's Fashion")
        self.assertTrue(self.seller.store_logo.name.endswith(".jpg"))
        with self.seller.store_logo.open("rb") as handle, Image.open(handle) as saved:
            self.assertFalse(saved.getexif())  # location data removed
        storefront = self.client.get(reverse("seller_storefront", args=[self.seller.pk]))
        self.assertContains(storefront, "Selina&#x27;s Fashion")
        self.assertContains(storefront, "Ladies wear in Osu.")
        self.assertContains(self.client.get(reverse("product_detail", args=[self.product.pk])), "Selina&#x27;s Fashion")

    def test_replacing_a_logo_deletes_the_old_file(self):
        self.client.force_login(self.seller)
        upload = lambda: SimpleUploadedFile("logo.png", png_bytes(), content_type="image/png")  # noqa: E731
        self.client.post(reverse("storefront_settings"), {"store_name": "Shop", "store_logo": upload()})
        self.seller.refresh_from_db()
        first = self.seller.store_logo
        storage, first_name = first.storage, first.name
        self.client.post(reverse("storefront_settings"), {"store_name": "Shop", "store_logo": upload()})
        self.seller.refresh_from_db()
        self.assertNotEqual(self.seller.store_logo.name, first_name)
        self.assertFalse(storage.exists(first_name))

    def test_rejects_non_images_and_oversized_files(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("storefront_settings"), {
            "store_name": "Shop", "store_cover": SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["store_cover"])
        big = SimpleUploadedFile("big.jpg", b"0" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
        response = self.client.post(reverse("storefront_settings"), {"store_name": "Shop", "store_cover": big})
        self.assertContains(response, "5 MB or smaller")

    def test_account_deletion_clears_storefront(self):
        User.objects.filter(pk=self.seller.pk).update(store_name="Selina's", store_description="About")
        self.seller.refresh_from_db()
        trust.delete_account(self.seller)
        self.seller.refresh_from_db()
        self.assertEqual((self.seller.store_name, self.seller.store_description), ("", ""))


class PasswordChangeTests(PortalBase):
    def test_needs_current_password_and_keeps_session(self):
        self.client.login(username="buyer", password=PASSWORD)
        response = self.client.post(reverse("password_change"), {
            "old_password": "wrong", "new_password1": "Another-strong-pass-91", "new_password2": "Another-strong-pass-91",
        })
        self.assertEqual(response.status_code, 200)
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password(PASSWORD))
        response = self.client.post(reverse("password_change"), {
            "old_password": PASSWORD, "new_password1": "Another-strong-pass-91", "new_password2": "Another-strong-pass-91",
        })
        self.assertRedirects(response, reverse("account_settings"))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password("Another-strong-pass-91"))
        self.assertEqual(self.client.get(reverse("account_overview")).status_code, 200)


class HomeBannerTests(PortalBase):
    def make_banner(self, title, **extra):
        values = {"image": "banners/x.jpg", "link_url": "/listings/", "starts_at": timezone.now() - timedelta(days=1)}
        values.update(extra)
        return HomeBanner.objects.create(title=title, **values)

    def test_only_live_banners_show_on_homepage(self):
        self.make_banner("Running", is_sponsored=True)
        self.make_banner("Ended", ends_at=timezone.now() - timedelta(hours=1))
        self.make_banner("Future", starts_at=timezone.now() + timedelta(days=1))
        self.make_banner("Switched off", is_active=False)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Running")
        self.assertContains(response, "Sponsored")
        for hidden in ("Ended", "Future", "Switched off"):
            self.assertNotContains(response, hidden)

    def test_links_must_be_site_paths_or_https(self):
        for bad in ("javascript:alert(1)", "//evil.example", "http://plain.example"):
            banner = HomeBanner(title="x", image="banners/x.jpg", link_url=bad, starts_at=timezone.now())
            with self.assertRaises(ValidationError):
                banner.full_clean()
        for good in ("/listings/?category=fashion", "https://partner.example/offer"):
            HomeBanner(title="x", image="banners/x.jpg", link_url=good, starts_at=timezone.now()).full_clean()


class StaffRoleTests(TestCase):
    def setUp(self):
        setup_staff_roles()

    def staff(self, username, role):
        user = User.objects.create_user(username, f"{username}@example.com", PASSWORD, is_staff=True)
        user.groups.add(Group.objects.get(name=role))
        self.client.force_login(user)
        return user

    def test_roles_are_created_and_refreshing_keeps_members(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(ROLES))
        member = self.staff("mod", "Moderator")
        moderator = Group.objects.get(name="Moderator")
        moderator.permissions.clear()
        call_command("setup_staff_roles", stdout=io.StringIO())
        self.assertIn(member, moderator.user_set.all())
        self.assertTrue(moderator.permissions.filter(codename="change_product").exists())

    def test_moderator_reviews_listings_but_cannot_see_money(self):
        self.staff("mod", "Moderator")
        self.assertEqual(self.client.get(reverse("admin:marketplace_product_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:commerce_payment_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_group_changelist")).status_code, 403)

    def test_support_agent_is_read_only_on_listings(self):
        self.staff("help", "Support agent")
        self.assertEqual(self.client.get(reverse("admin:marketplace_supportrequest_changelist")).status_code, 200)
        user = User.objects.get(username="help")
        self.assertFalse(user.has_perm("marketplace.change_product"))
        self.assertTrue(user.has_perm("marketplace.view_product"))

    def test_finance_can_refund_but_not_moderate(self):
        user = self.staff("cash", "Finance")
        self.assertEqual(self.client.get(reverse("admin:commerce_payment_changelist")).status_code, 200)
        self.assertTrue(user.has_perm("commerce.add_refund"))
        self.assertFalse(user.has_perm("marketplace.change_product"))

    def test_no_role_can_manage_staff_or_permissions(self):
        for role in ROLES:
            group = Group.objects.get(name=role)
            self.assertFalse(group.permissions.filter(content_type__app_label="auth").exists(), role)

    def test_administrator_manages_banners(self):
        self.staff("admin2", "Administrator")
        self.assertEqual(self.client.get(reverse("admin:marketplace_homebanner_add")).status_code, 200)
