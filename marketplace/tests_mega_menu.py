from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .catalog import category_menu
from .models import Category, GhanaRegion, Product, User

PASSWORD = "A-strong-password-482!"


class MegaMenuTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.phones = Category.objects.get(slug="phones-tech")
        self.mobile = self.phones.children.get(slug="mobile-phones")

    def make(self, **extra):
        return Product.objects.create(seller=self.seller, title="Phone", description="x", category=self.phones,
                                      price="100", city="Accra", region=GhanaRegion.GREATER_ACCRA, **extra)

    def menu_entry(self):
        return next(c for c in category_menu() if c["slug"] == "phones-tech")

    def test_counts_only_live_real_ads_and_update_straight_away(self):
        self.assertEqual(self.menu_entry()["count"], 0)
        self.make(status=Product.Status.PUBLISHED, subcategory=self.mobile)
        self.make(status=Product.Status.PENDING, subcategory=self.mobile)
        self.make(status=Product.Status.PUBLISHED, subcategory=self.mobile, is_demo=True)
        entry = self.menu_entry()
        self.assertEqual(entry["count"], 1)
        self.assertEqual(next(s for s in entry["children"] if s["slug"] == "mobile-phones")["count"], 1)

    def test_menu_renders_both_panes(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-mega-target="mega-phones-tech"')
        self.assertContains(response, 'id="mega-phones-tech"')
        self.assertContains(response, "Mobile phones")
        self.assertContains(response, "&amp;sub=mobile-phones")
