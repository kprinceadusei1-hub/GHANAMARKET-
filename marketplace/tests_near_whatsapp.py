import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import GhanaRegion, Product, User

PASSWORD = "A-strong-password-482!"


def listing(seller, title, city, region):
    return Product.objects.create(seller=seller, title=title, description="x", category_id="home-living",
                                  price="100", city=city, region=region, status=Product.Status.PUBLISHED)


class NearMeTests(TestCase):
    def setUp(self):
        seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.far = listing(seller, "Kumasi chair", "Kumasi", GhanaRegion.ASHANTI)
        self.region = listing(seller, "Tema chair", "Tema", GhanaRegion.GREATER_ACCRA)
        self.town = listing(seller, "Madina chair", "Madina", GhanaRegion.GREATER_ACCRA)
        Product.objects.filter(pk=self.town.pk).update(created_at=self.far.created_at)  # oldest of the three

    def titles(self, response):
        return [p.title for p in response.context["products"]]

    def test_visitor_sets_area_and_gets_nearest_first(self):
        url = reverse("product_list")
        self.assertNotIn("nearest", dict(self.client.get(url).context["sort_options"]))
        self.client.post(reverse("set_area"), {"region": "Greater Accra", "town": "madina", "next": url})
        self.assertEqual(self.client.session["buyer_area"], {"town": "Madina", "region": "Greater Accra"})
        response = self.client.get(url, {"sort": "nearest"})
        self.assertEqual(self.titles(response), ["Madina chair", "Tema chair", "Kumasi chair"])
        near = self.client.get(url, {"near": "1"})
        self.assertEqual(self.titles(near), ["Madina chair", "Tema chair"])
        self.assertContains(near, "near Madina, Greater Accra")

    def test_profile_location_is_used_when_signed_in(self):
        buyer = User.objects.create_user("b", "b@example.com", PASSWORD, city="Kumasi", region=GhanaRegion.ASHANTI)
        self.client.force_login(buyer)
        self.assertEqual(self.titles(self.client.get(reverse("product_list"), {"near": "1"})), ["Kumasi chair"])
        self.assertContains(self.client.get(reverse("home")), "Near you in Ashanti")

    def test_bad_input_is_rejected_and_clear_works(self):
        self.client.post(reverse("set_area"), {"region": "Narnia", "next": "https://evil.example/"})
        self.assertNotIn("buyer_area", self.client.session)
        response = self.client.post(reverse("set_area"), {"region": "Ashanti", "next": "https://evil.example/"})
        self.assertEqual(response.url, reverse("product_list"))
        self.client.post(reverse("set_area"), {"clear": "1"})
        self.assertNotIn("buyer_area", self.client.session)
        # Without an area, near=1 is ignored rather than hiding everything.
        self.assertEqual(len(self.titles(self.client.get(reverse("product_list"), {"near": "1"}))), 3)


class WhatsAppTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER,
                                               phone_number="024 111 2222")
        self.product = listing(self.seller, "Fridge", "Accra", GhanaRegion.GREATER_ACCRA)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD)
        self.url = reverse("product_detail", args=[self.product.pk])

    def test_number_format(self):
        for raw, expected in (("024 111 2222", "233241112222"), ("+233 24 111 2222", "233241112222"), ("12345", "")):
            self.assertEqual(User(phone_number=raw).whatsapp_number, expected)

    def test_share_for_everyone_contact_only_when_seller_opts_in(self):
        response = self.client.get(self.url)
        self.assertIn("wa.me/?text=", response.context["whatsapp_share_url"])
        self.assertNotIn("whatsapp_contact_url", response.context)
        self.client.force_login(self.buyer)
        self.assertNotContains(self.client.get(self.url), "233241112222")

        User.objects.filter(pk=self.seller.pk).update(whatsapp_contact=True)
        self.assertTrue(self.client.get(self.url).context["whatsapp_contact_url"].startswith("https://wa.me/233241112222"))
        self.client.logout()
        anonymous = self.client.get(self.url)
        self.assertTrue(anonymous.context["whatsapp_contact_url"].startswith(reverse("login")))
        self.assertNotContains(anonymous, "233241112222")

    def test_previews_have_no_whatsapp(self):
        User.objects.filter(pk=self.seller.pk).update(whatsapp_contact=True)
        Product.objects.filter(pk=self.product.pk).update(is_demo=True)
        response = self.client.get(self.url)
        self.assertNotIn("whatsapp_share_url", response.context)
        self.assertNotIn("whatsapp_contact_url", response.context)

    def test_opt_in_needs_a_ghana_number(self):
        self.client.force_login(self.seller)
        data = {"first_name": "", "last_name": "", "email": "s@example.com", "phone_number": "123",
                "whatsapp_contact": "on", "city": "Madina", "region": "Greater Accra"}
        response = self.client.post(reverse("account_settings"), data)
        self.assertContains(response, "Enter a Ghana mobile number")
        data["phone_number"] = "0241112222"
        self.client.post(reverse("account_settings"), data)
        self.assertTrue(User.objects.get(pk=self.seller.pk).whatsapp_contact)

    def test_whatsapp_option_is_only_for_sellers(self):
        self.client.force_login(self.buyer)
        self.assertNotContains(self.client.get(reverse("account_settings")), "contact me on WhatsApp")
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("account_settings")), "contact me on WhatsApp")


class RegisterPageTests(TestCase):
    def test_role_cards_and_seller_preselect(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, 'type="radio" name="role" value="buyer"')
        self.assertContains(response, 'type="hidden" name="country"')
        seller = self.client.get(reverse("register"), {"role": "seller"})
        self.assertEqual(seller.context["form"]["role"].value(), "seller")

    def test_country_defaults_to_ghana(self):
        self.client.post(reverse("register"), {
            "username": "kofi", "email": "kofi@example.com", "role": "buyer",
            "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertEqual(User.objects.get(username="kofi").country, "GH")


class EnsureSuperuserTests(TestCase):
    def test_creates_once_and_never_changes_password(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "owner", "DJANGO_SUPERUSER_EMAIL": "o@example.com",
               "DJANGO_SUPERUSER_PASSWORD": PASSWORD}
        with mock.patch.dict(os.environ, env):
            call_command("ensure_superuser", stdout=StringIO())
            owner = User.objects.get(username="owner")
            self.assertTrue(owner.is_superuser)
            owner.set_password("changed-later-123!")
            owner.save()
            call_command("ensure_superuser", stdout=StringIO())
        self.assertTrue(User.objects.get(username="owner").check_password("changed-later-123!"))
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_USERNAME": ""}):
            call_command("ensure_superuser", stdout=StringIO())
        self.assertEqual(User.objects.count(), 1)
