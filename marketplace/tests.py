from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.core.management import call_command
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ImproperlyConfigured
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from pathlib import Path
from config.settings import postgres_database_config

from .models import (
    Conversation,
    GhanaRegion,
    ListingReport,
    Message,
    Product,
    ProductPhoto,
    User,
)
from .forms import MAX_PRODUCT_IMAGE_SIZE
from .management.commands.seed_demo_marketplace import DEMO_LISTINGS


def sample_product_image():
    path = Path(__file__).parent / "static" / "marketplace" / "demo" / "smartphone-display.jpg"
    return SimpleUploadedFile(
        "sample-product.jpg", path.read_bytes(), content_type="image/jpeg"
    )


class DatabaseUrlConfigurationTests(SimpleTestCase):
    def test_postgres_database_url_is_parsed_without_losing_credentials_or_ssl(self):
        config = postgres_database_config(
            "postgresql://market-user:p%40ssword@db.example.test:5433/marketplace?sslmode=require"
        )
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "marketplace")
        self.assertEqual(config["USER"], "market-user")
        self.assertEqual(config["PASSWORD"], "p@ssword")
        self.assertEqual(config["HOST"], "db.example.test")
        self.assertEqual(config["PORT"], "5433")
        self.assertEqual(config["OPTIONS"], {"sslmode": "require"})

    def test_postgres_database_url_rejects_missing_database_or_unknown_options(self):
        with self.assertRaises(ImproperlyConfigured):
            postgres_database_config("postgres://db.example.test/")
        with self.assertRaises(ImproperlyConfigured):
            postgres_database_config("postgres://db.example.test/marketplace?fallback=sqlite")


class BasicPageTests(TestCase):
    def test_homepage_returns_success(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_shared_layout_has_keyboard_skip_link_and_mobile_navigation(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, 'id="main-content"')
        self.assertContains(response, 'aria-label="Quick navigation"')
        self.assertContains(response, "Browse")
        self.assertContains(response, "Sell")

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class AccountTests(TestCase):
    def test_registration_creates_buyer_account_and_logs_in(self):
        response = self.client.post(reverse("register"), {
            "username": "ama",
            "email": "ama@example.com",
            "first_name": "Ama",
            "last_name": "Mensah",
            "role": User.Role.BUYER,
            "country": "GH",
            "region": GhanaRegion.GREATER_ACCRA,
            "password1": "A-strong-password-482!",
            "password2": "A-strong-password-482!",
        })
        user = User.objects.get(username="ama")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(user.role, User.Role.BUYER)
        self.assertEqual(user.region, GhanaRegion.GREATER_ACCRA)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_seller_registration_creates_a_pending_seller_request(self):
        data = {
            "username": "kojo",
            "email": "kojo@example.com",
            "first_name": "Kojo",
            "role": User.Role.SELLER,
            "phone_number": "0240000000",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
            "country": "GH",
            "password1": "A-strong-password-482!",
            "password2": "A-strong-password-482!",
        }
        response = self.client.post(reverse("register"), data)
        seller = User.objects.get(username="kojo")
        self.assertRedirects(response, reverse("seller_listings"))
        self.assertEqual(seller.role, User.Role.SELLER)
        self.assertEqual(seller.seller_status, User.SellerStatus.PENDING)
        self.assertEqual(seller.phone_number, "0240000000")
        self.assertEqual(seller.region, GhanaRegion.ASHANTI)

    def test_seller_registration_requires_contact_location_details(self):
        response = self.client.post(reverse("register"), {
            "username": "incomplete-seller",
            "email": "incomplete@example.com",
            "role": User.Role.SELLER,
            "country": "GH",
            "password1": "A-strong-password-482!",
            "password2": "A-strong-password-482!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="incomplete-seller").exists())
        self.assertContains(response, "Required for seller accounts.", count=3)

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="first", email="same@example.com", password="A-strong-password-482!"
        )
        response = self.client.post(reverse("register"), {
            "username": "second",
            "email": "SAME@example.com",
            "role": User.Role.SELLER,
            "country": "GH",
            "password1": "A-strong-password-482!",
            "password2": "A-strong-password-482!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_login_and_post_logout(self):
        User.objects.create_user(
            username="seller", email="seller@example.com",
            password="A-strong-password-482!", role=User.Role.SELLER
        )
        response = self.client.post(reverse("login"), {
            "username": "seller",
            "password": "A-strong-password-482!",
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_authenticated_user_can_update_profile_settings(self):
        user = User.objects.create_user(
            username="profile-buyer", email="profile@example.com",
            password="A-strong-password-482!", role=User.Role.BUYER,
        )
        self.client.force_login(user)
        response = self.client.post(reverse("account_settings"), {
            "first_name": "Ama", "last_name": "Mensah", "email": "AMA@EXAMPLE.COM",
            "phone_number": "0240000000", "city": "Accra", "region": GhanaRegion.GREATER_ACCRA,
        })
        self.assertRedirects(response, reverse("account_settings"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Ama")
        self.assertEqual(user.email, "ama@example.com")

    def test_buyer_can_set_up_seller_account_before_posting(self):
        buyer = User.objects.create_user(
            username="new-seller", email="new-seller@example.com",
            password="A-strong-password-482!", role=User.Role.BUYER,
        )
        self.client.force_login(buyer)
        response = self.client.post(reverse("become_seller"), {
            "phone_number": "0240000000",
            "city": "Accra",
            "region": GhanaRegion.GREATER_ACCRA,
        })
        self.assertRedirects(response, reverse("seller_listings"))
        buyer.refresh_from_db()
        self.assertEqual(buyer.role, User.Role.SELLER)
        self.assertEqual(buyer.seller_status, User.SellerStatus.PENDING)
        self.assertEqual(buyer.phone_number, "0240000000")
        self.assertEqual(buyer.city, "Accra")
        self.assertEqual(buyer.region, GhanaRegion.GREATER_ACCRA)

    def test_seller_setup_requires_contact_and_location_details(self):
        buyer = User.objects.create_user(
            username="incomplete-upgrade", email="incomplete-upgrade@example.com",
            password="A-strong-password-482!", role=User.Role.BUYER,
        )
        self.client.force_login(buyer)
        response = self.client.post(reverse("become_seller"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.", count=3)
        buyer.refresh_from_db()
        self.assertEqual(buyer.role, User.Role.BUYER)

    def test_profile_settings_require_login_and_seller_location(self):
        response = self.client.get(reverse("account_settings"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('account_settings')}")
        seller = User.objects.create_user(
            username="profile-seller", email="profile-seller@example.com",
            password="A-strong-password-482!", role=User.Role.SELLER,
            phone_number="0240000000", city="Accra", region=GhanaRegion.GREATER_ACCRA,
        )
        self.client.force_login(seller)
        response = self.client.post(reverse("account_settings"), {
            "first_name": "Kojo", "last_name": "", "email": seller.email,
            "phone_number": "", "city": "", "region": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Required for seller accounts.")
        seller.refresh_from_db()
        self.assertEqual(seller.city, "Accra")


class ProductListingTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username="seller", email="seller@example.com",
            password="A-strong-password-482!", role=User.Role.SELLER,
            city="Accra", country="GH"
        )
        self.buyer = User.objects.create_user(
            username="buyer", email="buyer@example.com",
            password="A-strong-password-482!", role=User.Role.BUYER
        )
        self.product = Product.objects.create(
            seller=self.seller,
            title="Handmade basket",
            description="A woven basket made in Ghana.",
            category_id=Product.Category.HOME_LIVING,
            condition=Product.Condition.NEW,
            price="45.00",
            currency="GHS",
            city="Accra",
            region=GhanaRegion.GREATER_ACCRA,
            country="GH",
            status=Product.Status.PUBLISHED,
        )

    def test_product_card_uses_a_small_location_svg_and_guest_save_link(self):
        response = self.client.get(reverse("product_list"))

        self.assertContains(response, 'class="icon product-location-icon"')
        self.assertContains(response, "Accra, Greater Accra")
        self.assertContains(response, "Log in to save Handmade basket")

    def test_seller_listing_and_edits_wait_for_admin_approval(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), {
            "title": "Wooden stool",
            "description": "Handmade wooden stool.",
            "category": Product.Category.HOME_LIVING,
            "brand": "Local craft",
            "model": "Stool 01",
            "condition": Product.Condition.GOOD,
            "price": "125.50",
            "price_negotiable": "on",
            "included_items": "Care guide",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
            "images": [sample_product_image(), sample_product_image()],
        })
        created = Product.objects.get(title="Wooden stool")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(created.seller, self.seller)
        self.assertEqual(created.status, Product.Status.PENDING)
        self.assertEqual(created.currency, "GHS")
        self.assertEqual(created.country, "GH")
        self.assertEqual(created.region, GhanaRegion.ASHANTI)
        self.assertEqual(created.brand, "Local craft")
        self.assertEqual(created.model, "Stool 01")
        self.assertTrue(created.price_negotiable)
        self.assertEqual(created.included_items, "Care guide")
        self.assertTrue(created.image)
        self.assertEqual(created.photos.count(), 1)

        response = self.client.post(reverse("product_update", args=[created.pk]), {
            "title": "Updated stool",
            "description": "Updated description.",
            "category": Product.Category.HOME_LIVING,
            "condition": Product.Condition.GOOD,
            "price": "130.00",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
        })
        created.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(created.title, "Updated stool")
        self.assertEqual(created.price, 130)
        self.assertEqual(created.status, Product.Status.PENDING)
        self.assertFalse(created.price_negotiable)

    def test_new_listing_requires_a_photo_and_a_region(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), {
            "title": "Listing without details",
            "description": "A listing missing a photo and region.",
            "category": Product.Category.HOME_LIVING,
            "condition": Product.Condition.GOOD,
            "price": "125.50",
            "city": "Kumasi",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Listing without details").exists())
        self.assertContains(response, "Upload at least one photo of the item.")
        self.assertContains(response, "This field is required.")

    def test_seller_can_add_more_photos_when_editing_a_listing(self):
        self.product.image = sample_product_image()
        self.product.save()
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_update", args=[self.product.pk]), {
            "title": self.product.title,
            "description": self.product.description,
            "category": self.product.category_id,
            "condition": self.product.condition,
            "price": self.product.price,
            "city": self.product.city,
            "region": self.product.region,
            "images": [sample_product_image(), sample_product_image()],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.photos.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.photos.count(), 2)

    def test_listing_cannot_have_more_than_eight_photos(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), {
            "title": "Too many photos",
            "description": "A listing with too many photos.",
            "category": Product.Category.HOME_LIVING,
            "condition": Product.Condition.GOOD,
            "price": "125.50",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
            "images": [sample_product_image() for _ in range(9)],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Too many photos").exists())
        self.assertContains(response, "Upload no more than 8 photos at a time.")

    def test_listing_rejects_an_image_over_the_size_limit(self):
        self.client.force_login(self.seller)
        oversized_image = SimpleUploadedFile(
            "too-large.jpg",
            b"x" * (MAX_PRODUCT_IMAGE_SIZE + 1),
            content_type="image/jpeg",
        )
        response = self.client.post(reverse("product_create"), {
            "title": "Oversized photo listing",
            "description": "A listing with an oversized image.",
            "category": Product.Category.HOME_LIVING,
            "condition": Product.Condition.GOOD,
            "price": "125.50",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
            "images": [oversized_image],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Oversized photo listing").exists())
        self.assertContains(response, "Each photo must be 5 MB or smaller.")

    def test_listing_rejects_non_image_uploads(self):
        self.client.force_login(self.seller)
        invalid_image = SimpleUploadedFile(
            "not-an-image.jpg", b"not an image", content_type="image/jpeg"
        )
        response = self.client.post(reverse("product_create"), {
            "title": "Invalid photo listing",
            "description": "A listing with a non-image upload.",
            "category": Product.Category.HOME_LIVING,
            "condition": Product.Condition.GOOD,
            "price": "125.50",
            "city": "Kumasi",
            "region": GhanaRegion.ASHANTI,
            "images": [invalid_image],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Invalid photo listing").exists())
        self.assertContains(response, "Upload a valid image")

    def test_listing_detail_shows_additional_photos(self):
        self.product.image = sample_product_image()
        self.product.save()
        ProductPhoto.objects.create(
            product=self.product, image=sample_product_image(), position=1
        )
        response = self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.assertContains(response, "photo-thumbnails")
        self.assertContains(response, "photo 2")
        self.assertContains(response, "data-gallery-next")
        self.assertContains(response, "data-gallery-count")

    def test_product_search_matches_brand_and_model(self):
        self.product.brand = "Nokia"
        self.product.model = "G42"
        self.product.save()
        response = self.client.get(reverse("product_list"), {"q": "Nokia"})
        self.assertContains(response, "Handmade basket")

    def test_seller_dashboard_shows_private_listing_counts_and_management_actions(self):
        pending = Product.objects.create(
            seller=self.seller,
            title="Waiting for review",
            description="A pending listing.",
            category_id=Product.Category.OTHER,
            price="10.00",
            city="Accra",
            status=Product.Status.PENDING,
        )
        rejected = Product.objects.create(
            seller=self.seller,
            title="Needs a better photo",
            description="A listing returned for changes.",
            category_id=Product.Category.OTHER,
            price="15.00",
            city="Accra",
            status=Product.Status.REJECTED,
            moderation_note="Please add clearer photos.",
        )
        self.client.force_login(self.seller)

        response = self.client.get(reverse("seller_listings"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["counts"]["total"], 3)
        self.assertEqual(response.context["counts"]["live"], 1)
        self.assertEqual(response.context["counts"]["pending"], 1)
        self.assertEqual(response.context["counts"]["needs_changes"], 1)
        self.assertContains(response, "Your listings")
        self.assertContains(response, "Please add clearer photos.")
        self.assertContains(response, reverse("product_update", args=[pending.pk]))

    def test_seller_can_deactivate_and_resubmit_only_their_own_listing(self):
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("seller_listing_status", args=[self.product.pk]),
            {"action": "deactivate"},
        )
        self.assertRedirects(response, reverse("seller_listings"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.DRAFT)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertFalse(Product.objects.filter(pk=self.product.pk, status=Product.Status.PUBLISHED).exists())

        self.client.post(
            reverse("seller_listing_status", args=[self.product.pk]),
            {"action": "reactivate"},
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_seller_cannot_deactivate_another_sellers_listing(self):
        other_seller = User.objects.create_user(
            username="other-seller", email="other-seller@example.com",
            password="A-strong-password-482!", role=User.Role.SELLER,
        )
        other_product = Product.objects.create(
            seller=other_seller, title="Other seller item", description="Private ownership test.",
            category_id=Product.Category.OTHER, price="25.00", city="Accra",
            status=Product.Status.PUBLISHED,
        )
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("seller_listing_status", args=[other_product.pk]),
            {"action": "deactivate"},
        )
        self.assertEqual(response.status_code, 404)
        other_product.refresh_from_db()
        self.assertEqual(other_product.status, Product.Status.PUBLISHED)

    def test_seller_dashboard_filters_listings_without_changing_summary_counts(self):
        Product.objects.create(
            seller=self.seller,
            title="Waiting for review",
            description="A pending listing.",
            category_id=Product.Category.OTHER,
            price="10.00",
            city="Accra",
            status=Product.Status.PENDING,
        )
        self.client.force_login(self.seller)

        response = self.client.get(
            reverse("seller_listings"), {"status": Product.Status.PENDING}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["products"]), 1)
        self.assertEqual(response.context["products"][0].status, Product.Status.PENDING)
        self.assertEqual(response.context["counts"]["total"], 2)

    def test_region_filter_limits_results_to_selected_region(self):
        Product.objects.create(
            seller=self.seller,
            title="Cape Coast bowl",
            description="A locally made bowl.",
            category_id=Product.Category.HOME_LIVING,
            price="55.00",
            city="Cape Coast",
            region=GhanaRegion.CENTRAL,
            country="GH",
            status=Product.Status.PUBLISHED,
        )
        self.product.region = GhanaRegion.GREATER_ACCRA
        self.product.save()
        response = self.client.get(
            reverse("product_list"), {"region": GhanaRegion.CENTRAL}
        )
        self.assertContains(response, "Cape Coast bowl")
        self.assertNotContains(response, "Handmade basket")
        self.assertContains(response, "1 listing in Central")

    def test_price_and_condition_filters_combine(self):
        self.product.condition = Product.Condition.NEW
        self.product.price = "45.00"
        self.product.save()
        response = self.client.get(reverse("product_list"), {
            "min_price": "40", "max_price": "50", "condition": Product.Condition.NEW,
        })
        self.assertContains(response, "Handmade basket")
        response = self.client.get(reverse("product_list"), {
            "min_price": "46", "max_price": "50", "condition": Product.Condition.NEW,
        })
        self.assertNotContains(response, "Handmade basket")

    def test_buyer_can_save_and_remove_a_published_listing(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("toggle_favorite", args=[self.product.pk]))
        self.assertRedirects(response, reverse("product_detail", args=[self.product.pk]))
        self.assertContains(self.client.get(reverse("saved_listings")), "Handmade basket")
        self.client.post(reverse("toggle_favorite", args=[self.product.pk]))
        self.assertNotContains(self.client.get(reverse("saved_listings")), "Handmade basket")

    def test_browse_page_shows_readable_category_and_filter_controls(self):
        response = self.client.get(
            reverse("product_list"),
            {"category": Product.Category.HOME_LIVING},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All")
        self.assertContains(response, "Home &amp; Living")
        self.assertContains(response, "Find listings")
        self.assertContains(response, 'aria-label="Browse by category"')

    def test_homepage_exposes_all_sixteen_regions(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(len(response.context["regions"]), 16)
        for _, label in GhanaRegion.choices:
            self.assertContains(response, label)

    def test_homepage_shows_category_counts_and_photo_count_for_live_listings(self):
        self.product.image = sample_product_image()
        self.product.save()
        ProductPhoto.objects.create(
            product=self.product, image=sample_product_image(), position=1
        )
        Product.objects.create(
            seller=self.seller,
            title="Private listing",
            description="Still awaiting approval.",
            category_id=Product.Category.HOME_LIVING,
            price="30.00",
            city="Accra",
            status=Product.Status.PENDING,
        )

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 photos")
        self.assertContains(response, "Handmade basket")
        home_living = next(
            category
            for category in response.context["categories"]
            if category["value"] == Product.Category.HOME_LIVING
        )
        self.assertEqual(home_living["count"], 1)
        self.assertNotContains(response, "Private listing")
        self.assertContains(response, "Shop by Category")
        self.assertContains(response, "Every ad reviewed")
        self.assertContains(response, "Explore Ghana by region")
        self.assertContains(response, "?region=Greater%20Accra")

    def test_buyer_cannot_create_listing(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("product_create"), {
            "title": "Not allowed",
        })
        self.assertRedirects(response, reverse("home"))
        self.assertFalse(Product.objects.filter(title="Not allowed").exists())

    def test_seller_cannot_edit_another_sellers_listing(self):
        other_seller = User.objects.create_user(
            username="other-seller", email="other@example.com",
            password="A-strong-password-482!", role=User.Role.SELLER
        )
        self.client.force_login(other_seller)
        response = self.client.get(reverse("product_update", args=[self.product.pk]))
        self.assertEqual(response.status_code, 404)

    def test_search_only_shows_matching_published_listings(self):
        Product.objects.create(
            seller=self.seller,
            title="Hidden basket",
            description="Not published.",
            category_id=Product.Category.HOME_LIVING,
            price="20.00",
            city="Accra",
            country="GH",
            status=Product.Status.DRAFT,
        )
        response = self.client.get(reverse("product_list"), {"q": "handmade"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Handmade basket")
        self.assertNotContains(response, "Hidden basket")

    def test_location_filter_matches_city_case_insensitively(self):
        Product.objects.create(
            seller=self.seller,
            title="Kumasi chair",
            description="A sturdy chair.",
            category_id=Product.Category.HOME_LIVING,
            price="75.00",
            city="Kumasi",
            country="GH",
            status=Product.Status.PUBLISHED,
        )
        response = self.client.get(reverse("product_list"), {"city": "kUmaSi"})
        self.assertContains(response, "Kumasi chair")
        self.assertNotContains(response, "Handmade basket")
        self.assertContains(response, "1 listing in kUmaSi")

    def test_price_sort_orders_listings_and_invalid_sort_defaults_to_recent(self):
        cheaper = Product.objects.create(
            seller=self.seller,
            title="Budget basket",
            description="An affordable basket.",
            category_id=Product.Category.HOME_LIVING,
            price="10.00",
            city="Accra",
            country="GH",
            status=Product.Status.PUBLISHED,
        )
        response = self.client.get(reverse("product_list"), {"sort": "price-low"})
        self.assertEqual(response.context["products"][0], cheaper)
        response = self.client.get(reverse("product_list"), {"sort": "unknown"})
        self.assertEqual(response.context["selected_sort"], "newest")

    def test_browse_pagination_shows_a_full_page_and_keeps_requested_page(self):
        from .views import LISTINGS_PER_PAGE

        for number in range(LISTINGS_PER_PAGE):
            Product.objects.create(
                seller=self.seller,
                title=f"Basket {number + 1}",
                description="A woven basket for pagination testing.",
                category_id=Product.Category.HOME_LIVING,
                condition=Product.Condition.NEW,
                price="45.00",
                city="Accra",
                region=GhanaRegion.GREATER_ACCRA,
                country="GH",
                status=Product.Status.PUBLISHED,
            )

        first_page = self.client.get(reverse("product_list"))
        self.assertEqual(first_page.context["result_count"], LISTINGS_PER_PAGE + 1)
        self.assertEqual(len(first_page.context["products"]), LISTINGS_PER_PAGE)
        self.assertContains(first_page, "Page <strong>1</strong> of 2")
        self.assertContains(first_page, "page=2")

        second_page = self.client.get(reverse("product_list"), {"page": 2})
        self.assertEqual(second_page.context["page"].number, 2)
        self.assertEqual(len(second_page.context["products"]), 1)

    def test_draft_is_hidden_from_public_but_visible_to_its_seller(self):
        self.product.status = Product.Status.DRAFT
        self.product.save()
        response = self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.seller)
        response = self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)


class MessagingTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username="seller",
            email="seller@example.com",
            password="A-strong-password-482!",
            role=User.Role.SELLER,
        )
        self.buyer = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="A-strong-password-482!",
            role=User.Role.BUYER,
        )
        self.other_buyer = User.objects.create_user(
            username="other-buyer",
            email="other@example.com",
            password="A-strong-password-482!",
            role=User.Role.BUYER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            title="Market bag",
            description="A handwoven market bag.",
            category_id=Product.Category.FASHION,
            price="30.00",
            city="Accra",
            country="GH",
            status=Product.Status.PUBLISHED,
        )

    def test_buyer_can_start_conversation_and_seller_can_reply(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("conversation_start", args=[self.product.pk]),
            {"body": "Is this bag still available?"},
        )
        conversation = Conversation.objects.get(product=self.product, buyer=self.buyer)
        self.assertRedirects(response, reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(conversation.seller, self.seller)
        self.assertEqual(conversation.messages.get().sender, self.buyer)

        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("conversation_detail", args=[conversation.pk]),
            {"body": "Yes, it is available."},
        )
        self.assertRedirects(response, reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(conversation.messages.count(), 2)
        self.assertContains(
            self.client.get(reverse("conversation_detail", args=[conversation.pk])),
            "Is this bag still available?",
        )
        self.assertContains(
            self.client.get(reverse("conversation_detail", args=[conversation.pk])),
            "Yes, it is available.",
        )

    def test_buyer_reuses_conversation_for_the_same_listing(self):
        self.client.force_login(self.buyer)
        url = reverse("conversation_start", args=[self.product.pk])
        self.client.post(url, {"body": "First question."})
        response = self.client.post(url, {"body": "A follow-up question."})
        self.assertEqual(Conversation.objects.filter(product=self.product).count(), 1)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(response.status_code, 302)

    def test_seller_cannot_start_conversation_with_self(self):
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("conversation_start", args=[self.product.pk]),
            {"body": "Hello."},
        )
        self.assertRedirects(response, reverse("product_detail", args=[self.product.pk]))
        self.assertFalse(Conversation.objects.exists())

    def test_seller_role_cannot_initiate_a_conversation(self):
        another_seller = User.objects.create_user(
            username="another-seller",
            email="another-seller@example.com",
            password="A-strong-password-482!",
            role=User.Role.SELLER,
        )
        self.client.force_login(another_seller)
        self.client.post(
            reverse("conversation_start", args=[self.product.pk]),
            {"body": "Hello."},
        )
        self.assertFalse(Conversation.objects.exists())

    def test_conversations_require_login_and_post_to_start(self):
        inbox = reverse("conversation_list")
        response = self.client.get(inbox)
        self.assertRedirects(response, f"{reverse('login')}?next={inbox}")
        response = self.client.get(reverse("conversation_start", args=[self.product.pk]))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('conversation_start', args=[self.product.pk])}",
        )
        self.client.force_login(self.buyer)
        self.client.get(reverse("conversation_start", args=[self.product.pk]))
        self.assertFalse(Conversation.objects.exists())

    def test_only_participants_can_read_or_send_messages(self):
        conversation = Conversation.objects.create(
            product=self.product, buyer=self.buyer, seller=self.seller
        )
        Message.objects.create(
            conversation=conversation, sender=self.buyer, body="Private question."
        )
        self.client.force_login(self.other_buyer)
        detail = reverse("conversation_detail", args=[conversation.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        response = self.client.post(detail, {"body": "Intruding."})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(conversation.messages.count(), 1)

    def test_cannot_start_conversation_about_unpublished_listing(self):
        self.product.status = Product.Status.DRAFT
        self.product.save()
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("conversation_start", args=[self.product.pk]),
            {"body": "Is this available?"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conversation.objects.exists())

    def test_blank_message_is_rejected(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("conversation_start", args=[self.product.pk]), {"body": "  "}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Conversation.objects.exists())

    def test_demo_products_cannot_receive_messages(self):
        self.product.is_demo = True
        self.product.save()
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("conversation_start", args=[self.product.pk]),
            {"body": "Is this available?"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conversation.objects.exists())
        detail = self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.assertContains(detail, "Preview listing")
        self.assertNotContains(detail, reverse("conversation_start", args=[self.product.pk]))


class ListingReportAndAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="site-admin",
            email="admin@example.com",
            password="A-strong-password-482!",
        )
        self.seller = User.objects.create_user(
            username="report-seller",
            email="report-seller@example.com",
            password="A-strong-password-482!",
            role=User.Role.SELLER,
        )
        self.buyer = User.objects.create_user(
            username="report-buyer",
            email="report-buyer@example.com",
            password="A-strong-password-482!",
            role=User.Role.BUYER,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            title="Phone for sale",
            description="A listing for testing admin review.",
            category_id=Product.Category.PHONES_TECH,
            price="200.00",
            city="Accra",
            region=GhanaRegion.GREATER_ACCRA,
            country="GH",
            status=Product.Status.PENDING,
        )

    def _admin_review_data(self, **overrides):
        data = {
            "seller": str(self.seller.pk),
            "title": self.product.title,
            "description": self.product.description,
            "category": self.product.category_id,
            "brand": self.product.brand,
            "model": self.product.model,
            "included_items": self.product.included_items,
            "condition": self.product.condition,
            "price": str(self.product.price),
            "currency": self.product.currency,
            "city": self.product.city,
            "region": self.product.region,
            "country": self.product.country,
            "moderation_note": "",
            "attributes": "{}",
            "photos-TOTAL_FORMS": "0",
            "photos-INITIAL_FORMS": "0",
            "photos-MIN_NUM_FORMS": "0",
            "photos-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_admin_home_has_live_marketplace_moderation_overview(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Marketplace workspace")
        self.assertContains(response, "Listings awaiting review")
        self.assertContains(response, "Pending approvals")
        self.assertContains(response, "Active listings")
        self.assertContains(response, "Live listings by category")
        self.assertContains(response, "Go to analytics")
        self.assertContains(response, "Admin navigation")

    def test_admin_user_add_page_uses_shared_marketplace_admin_theme(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin:marketplace_user_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/static/css/admin-review.css"')
        self.assertContains(response, 'href="/static/css/control-centre.css"')
        self.assertContains(response, "Marketplace Control")
        self.assertContains(response, "Marketplace profile")
        self.assertContains(response, "Admin navigation")

    def test_analytics_uses_real_non_demo_data_and_validates_period(self):
        self.product.status = Product.Status.PUBLISHED
        self.product.save()
        ListingReport.objects.create(
            product=self.product,
            reporter=self.buyer,
            reason=ListingReport.Reason.OTHER,
            details="Analytics fixture report.",
        )
        Product.objects.create(
            seller=self.seller,
            title="Preview row excluded",
            description="Preview only.",
            category_id=Product.Category.PHONES_TECH,
            price="10.00",
            city="Accra",
            country="GH",
            status=Product.Status.PUBLISHED,
            is_demo=True,
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("marketplace_admin_analytics"), {"period": "7"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period"], 7)
        self.assertEqual(response.context["listing_total"], 1)
        self.assertEqual(response.context["listing_live"], 1)
        self.assertEqual(len(response.context["listing_series"]), 7)
        self.assertEqual(response.context["report_activity_total"], 1)
        self.assertEqual(len(response.context["report_series"]), 7)
        self.assertContains(response, "Listing activity")
        self.assertContains(response, "Report activity")
        self.assertContains(response, "Payments and orders")
        self.assertNotContains(response, "Preview row excluded")

        for days in (30, 90):
            period_response = self.client.get(
                reverse("marketplace_admin_analytics"), {"period": str(days)}
            )
            self.assertEqual(period_response.context["period"], days)
            self.assertEqual(len(period_response.context["listing_series"]), days)

        invalid_period = self.client.get(reverse("marketplace_admin_analytics"), {"period": "365"})
        self.assertEqual(invalid_period.context["period"], 30)

    def test_analytics_denies_staff_without_marketplace_view_permissions(self):
        limited_staff = User.objects.create_user(
            username="limited-staff",
            email="limited-staff@example.com",
            password="A-strong-password-482!",
            is_staff=True,
        )
        self.client.force_login(limited_staff)
        response = self.client.get(reverse("marketplace_admin_analytics"))
        self.assertEqual(response.status_code, 403)

    def test_admin_account_actions_suspend_and_reactivate_only_member_accounts(self):
        protected_staff = User.objects.create_user(
            username="staff-account",
            email="staff-account@example.com",
            password="A-strong-password-482!",
            is_staff=True,
        )
        self.client.force_login(self.admin_user)
        user_list = reverse("admin:marketplace_user_changelist")

        self.client.post(user_list, {
            "action": "suspend_member_accounts",
            "_selected_action": [str(self.seller.pk), str(protected_staff.pk), str(self.admin_user.pk)],
        })
        self.seller.refresh_from_db()
        protected_staff.refresh_from_db()
        self.admin_user.refresh_from_db()
        self.assertFalse(self.seller.is_active)
        self.assertTrue(protected_staff.is_active)
        self.assertTrue(self.admin_user.is_active)
        self.assertTrue(LogEntry.objects.filter(
            user=self.admin_user, object_id=str(self.seller.pk), change_message__contains="suspended"
        ).exists())

        self.client.post(user_list, {
            "action": "reactivate_member_accounts",
            "_selected_action": [str(self.seller.pk)],
        })
        self.seller.refresh_from_db()
        self.assertTrue(self.seller.is_active)

    def test_admin_can_view_read_only_audit_log(self):
        LogEntry.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(Product),
            object_id=str(self.product.pk),
            object_repr=self.product.title,
            action_flag=2,
            change_message="Test admin audit record.",
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin:admin_logentry_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.title)
        self.assertContains(response, "Test admin audit record.")

    def test_pending_listing_is_private_until_admin_approves(self):
        detail_url = reverse("product_detail", args=[self.product.pk])
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(detail_url), "Awaiting admin approval")

        self.client.force_login(self.admin_user)
        change_url = reverse(
            "admin:marketplace_product_change", args=[self.product.pk]
        )
        self.product.image = sample_product_image()
        self.product.save()
        ProductPhoto.objects.create(
            product=self.product, image=sample_product_image(), position=1
        )
        ProductPhoto.objects.create(
            product=self.product, image=sample_product_image(), position=2
        )
        review_page = self.client.get(change_url)
        self.assertContains(review_page, "every uploaded photo")
        self.assertContains(review_page, self.seller.email)
        self.assertContains(review_page, "Main listing photo")
        self.assertContains(review_page, "Photo preview")
        self.assertContains(review_page, self.product.image.name)
        self.assertContains(review_page, "Approve and publish listing")
        response = self.client.post(
            change_url,
            self._admin_review_data(_approve_listing="1"),
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        self.client.logout()
        self.assertEqual(self.client.get(detail_url).status_code, 200)

    def test_admin_can_return_pending_listing_with_specific_change_note(self):
        self.client.force_login(self.admin_user)
        change_url = reverse(
            "admin:marketplace_product_change", args=[self.product.pk]
        )
        response = self.client.post(
            change_url,
            self._admin_review_data(
                moderation_note="Please upload a clear photo of the back of the phone.",
                _request_changes="1",
            ),
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.REJECTED)
        self.assertEqual(
            self.product.moderation_note,
            "Please upload a clear photo of the back of the phone.",
        )

    def test_admin_cannot_request_changes_without_explanation(self):
        self.client.force_login(self.admin_user)
        change_url = reverse(
            "admin:marketplace_product_change", args=[self.product.pk]
        )
        response = self.client.post(
            change_url,
            self._admin_review_data(_request_changes="1"),
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_admin_can_remove_a_published_listing_from_the_marketplace(self):
        self.product.status = Product.Status.PUBLISHED
        self.product.save()
        self.client.force_login(self.admin_user)
        change_url = reverse(
            "admin:marketplace_product_change", args=[self.product.pk]
        )

        response = self.client.post(
            change_url,
            self._admin_review_data(_remove_listing="1"),
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.DRAFT)
        self.assertEqual(
            self.product.moderation_note,
            "This listing was removed by an admin.",
        )
        self.assertTrue(LogEntry.objects.filter(
            user=self.admin_user,
            object_id=str(self.product.pk),
            change_message__contains="removed from the public marketplace",
        ).exists())

        response = self.client.post(
            change_url,
            self._admin_review_data(_restore_listing="1"),
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        self.assertEqual(self.product.moderation_note, "")

    def test_admin_product_queue_shows_pending_and_report_counts(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin:marketplace_product_changelist"))
        self.assertContains(response, "1")
        self.assertContains(response, "awaiting individual review")
        self.assertContains(response, "open buyer reports")

    def test_admin_listing_search_combined_filters_and_pagination(self):
        for number in range(25):
            Product.objects.create(
                seller=self.seller,
                title=f"Phone review item {number + 1}",
                description="A phone awaiting admin review.",
                category_id=Product.Category.PHONES_TECH,
                price="200.00",
                city="Accra",
                region=GhanaRegion.GREATER_ACCRA,
                country="GH",
                status=Product.Status.PENDING,
            )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:marketplace_product_changelist"), {
            "q": "Phone",
            "status__exact": Product.Status.PENDING,
            "category__exact": Product.Category.PHONES_TECH,
        })

        self.assertEqual(response.status_code, 200)
        changelist = response.context["cl"]
        self.assertEqual(changelist.result_count, 26)
        self.assertEqual(changelist.paginator.per_page, 25)
        self.assertEqual(changelist.paginator.num_pages, 2)
        self.assertContains(response, "Phone review item 1")

    def test_buyer_can_report_listing_and_admin_can_remove_it(self):
        self.product.status = Product.Status.PUBLISHED
        self.product.save()
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("report_listing", args=[self.product.pk]),
            {
                "reason": ListingReport.Reason.SCAM,
                "details": "The seller is asking for a deposit before a viewing.",
            },
        )
        self.assertRedirects(response, reverse("product_detail", args=[self.product.pk]))
        report = ListingReport.objects.get(product=self.product, reporter=self.buyer)
        self.assertEqual(report.status, ListingReport.Status.OPEN)

        self.client.force_login(self.admin_user)
        queue = reverse("admin:marketplace_listingreport_changelist")
        self.assertContains(self.client.get(queue), "1 open user report(s)")
        self.client.post(
            queue,
            {
                "action": "remove_reported_listings",
                "_selected_action": [str(report.pk)],
            },
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.DRAFT)
        report.refresh_from_db()
        self.assertEqual(report.status, ListingReport.Status.REVIEWED)
        self.assertTrue(LogEntry.objects.filter(
            user=self.admin_user,
            object_id=str(report.pk),
            change_message__contains="resolved",
        ).exists())

    def test_reporter_cannot_submit_duplicate_report(self):
        self.product.status = Product.Status.PUBLISHED
        self.product.save()
        self.client.force_login(self.buyer)
        report_url = reverse("report_listing", args=[self.product.pk])
        data = {"reason": ListingReport.Reason.SCAM, "details": "Please check this."}
        self.client.post(report_url, data)
        self.client.post(report_url, data)
        self.assertEqual(
            ListingReport.objects.filter(product=self.product, reporter=self.buyer).count(),
            1,
        )


class DemoMarketplaceCommandTests(TestCase):
    def test_seed_command_creates_visible_marked_preview_catalogue_idempotently(self):
        call_command("seed_demo_marketplace", verbosity=0)
        preview_seller = User.objects.get(username="marketplace-preview-seller")
        products = Product.objects.filter(seller=preview_seller)
        self.assertEqual(products.count(), len(DEMO_LISTINGS))
        self.assertTrue(all(products.values_list("is_demo", flat=True)))
        self.assertFalse(preview_seller.has_usable_password())
        self.assertTrue(all(
            default_storage.exists(product.image.name)
            for product in products
        ))
        self.assertTrue(all(
            product.image.name.endswith(".jpg") and product.region
            for product in products
        ))

        # With no real ads, the labelled preview catalogue fills the storefront.
        homepage = self.client.get(reverse("home"))
        browse_page = self.client.get(reverse("product_list"))
        self.assertContains(homepage, "Samsung Galaxy A15")
        self.assertContains(homepage, "Preview example")
        self.assertContains(homepage, "Preview listings are examples")
        self.assertEqual(browse_page.context["result_count"], len(DEMO_LISTINGS))

        # Previews stay visible next to real ads (until deleted); real ads come first.
        real_seller = User.objects.create_user(
            username="realseller", email="real@example.com", password="A-strong-password-482!", role=User.Role.SELLER,
        )
        Product.objects.create(
            seller=real_seller, title="Real fridge", description="Works.", category_id=Product.Category.HOME_LIVING,
            price="900.00", city="Accra", status=Product.Status.PUBLISHED,
        )
        homepage = self.client.get(reverse("home"))
        self.assertContains(homepage, "Real fridge")
        self.assertContains(homepage, "Preview example")
        browse = self.client.get(reverse("product_list"))
        self.assertEqual(browse.context["result_count"], len(DEMO_LISTINGS) + 1)
        self.assertEqual(browse.context["products"][0].title, "Real fridge")
        Product.objects.filter(title="Real fridge").delete()

        call_command("seed_demo_marketplace", verbosity=0)
        self.assertEqual(Product.objects.filter(seller=preview_seller).count(), len(DEMO_LISTINGS))


class DemoMarketplaceDeleteTests(TestCase):
    def test_delete_option_removes_previews_and_keeps_real_listings(self):
        call_command("seed_demo_marketplace", verbosity=0)
        seller = User.objects.create_user("real", "real@example.com", "A-strong-password-482!", role=User.Role.SELLER)
        Product.objects.create(seller=seller, title="Real chair", description="x", category_id="home-living",
                               price="50", city="Accra", status=Product.Status.PUBLISHED)
        house = Product.objects.get(title="3 Bedroom House for Sale - East Legon")
        self.assertEqual(house.attributes["listing_type"], "For sale")
        image_name = house.image.name

        call_command("seed_demo_marketplace", delete=True, verbosity=0)

        self.assertFalse(Product.objects.filter(is_demo=True).exists())
        self.assertFalse(User.objects.filter(username="marketplace-preview-seller").exists())
        self.assertTrue(Product.objects.filter(title="Real chair").exists())
        self.assertFalse(default_storage.exists(image_name))
