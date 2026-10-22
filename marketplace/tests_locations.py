from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import ProfileForm
from .ghana_places import clean_city
from .models import Conversation, GhanaRegion, Product, User

PASSWORD = "A-strong-password-482!"


class CleanCityTests(TestCase):
    def test_region_names_are_rejected(self):
        for value in ("greater accra", "Ashanti Region", "GHANA"):
            with self.assertRaises(ValidationError):
                clean_city(value)

    def test_known_towns_are_tidied(self):
        self.assertEqual(clean_city("  east   legon "), "East Legon")
        self.assertEqual(clean_city("KUMASI"), "Kumasi")
        self.assertEqual(clean_city("Abelemkpe"), "Abelemkpe")
        self.assertEqual(clean_city(""), "")

    def test_profile_form_offers_suggestions_and_validates(self):
        user = User.objects.create_user("ama", "ama@example.com", PASSWORD)
        form = ProfileForm(instance=user)
        self.assertEqual(form.fields["city"].widget.attrs["list"], "gh-towns")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("account_settings")), '<datalist id="gh-towns">')


class LocationDisplayTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER,
                                               city="Madina", region=GhanaRegion.GREATER_ACCRA)
        self.buyer = User.objects.create_user("buyer", "b@example.com", PASSWORD, city="Kumasi",
                                              region=GhanaRegion.ASHANTI)
        product = Product.objects.create(seller=self.seller, title="Fan", description="x", category_id="home-living",
                                         price="100", city="Madina", region=GhanaRegion.GREATER_ACCRA,
                                         status=Product.Status.PUBLISHED)
        self.conversation = Conversation.objects.create(product=product, buyer=self.buyer, seller=self.seller)

    def test_seller_sees_buyer_location_in_chats(self):
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("conversation_list")), "Kumasi, Ashanti")
        detail = reverse("conversation_detail", args=[self.conversation.pk])
        self.assertContains(self.client.get(detail), "Kumasi, Ashanti")

    def test_buyer_sees_seller_location_in_chats(self):
        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse("conversation_list")), "Madina, Greater Accra")

    def test_dashboard_counts_users_by_region_and_flags_bad_towns(self):
        User.objects.create_user("nowhere", "n@example.com", PASSWORD)
        User.objects.create_user("regiontown", "r@example.com", PASSWORD, role=User.Role.SELLER,
                                 city="greater accra", region=GhanaRegion.GREATER_ACCRA)
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:index"))
        locations = response.context["cc_locations"]
        rows = {row["region"]: row for row in locations["regions"]}
        self.assertEqual((rows["Greater Accra"]["buyers"], rows["Greater Accra"]["sellers"]), (0, 2))
        self.assertEqual((rows["Ashanti"]["buyers"], rows["Ashanti"]["sellers"]), (1, 0))
        self.assertEqual(locations["missing"], 1)
        self.assertEqual(locations["town_is_region"], 1)
        self.assertContains(response, "Where your users are")
