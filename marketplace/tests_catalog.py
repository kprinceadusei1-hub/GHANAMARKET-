from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .category_catalog import CATALOG
from .models import Category, CategoryAttribute, GhanaRegion, Product, SearchTerm, User
from .tests import sample_product_image

PASSWORD = "A-strong-password-482!"


class CatalogFixtures(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user(
            username="seller", email="seller@example.com", password=PASSWORD, role=User.Role.SELLER,
            city="Accra", region=GhanaRegion.GREATER_ACCRA, phone_number="0240000000",
        )
        self.buyer = User.objects.create_user(
            username="buyer", email="buyer@example.com", password=PASSWORD, role=User.Role.BUYER,
        )

    def listing(self, title, category="vehicles", sub=None, attributes=None, **extra):
        values = {
            "seller": self.seller, "title": title, "description": "Listing used in catalogue tests.",
            "category_id": category, "subcategory": Category.objects.get(slug=sub) if sub else None,
            "attributes": attributes or {}, "price": "100.00", "city": "Accra",
            "region": GhanaRegion.GREATER_ACCRA, "status": Product.Status.PUBLISHED,
        }
        values.update(extra)
        return Product.objects.create(**values)


class CategorySeedTests(CatalogFixtures):
    def test_migration_seeds_full_launch_catalogue(self):
        self.assertEqual(Category.objects.filter(parent__isnull=True).count(), len(CATALOG))
        cars = Category.objects.get(slug="cars")
        self.assertEqual(cars.parent.slug, "vehicles")
        self.assertIn("mileage", [a.key for a in cars.attribute_definitions()])

    def test_seed_command_is_idempotent_and_keeps_admin_edits(self):
        Category.objects.filter(slug="vehicles").update(name="Cars, Bikes & Trucks")
        call_command("seed_categories", verbosity=0)
        self.assertEqual(Category.objects.get(slug="vehicles").name, "Cars, Bikes & Trucks")
        self.assertEqual(Category.objects.filter(parent__isnull=True).count(), len(CATALOG))

    def test_inactive_category_is_hidden_from_navigation(self):
        Category.objects.filter(slug="jobs").update(is_active=False)
        response = self.client.get(reverse("home"))
        self.assertNotIn("jobs", [c["value"] for c in response.context["categories"]])


class BrowseFilterTests(CatalogFixtures):
    def test_subcategory_filter(self):
        self.listing("Toyota Corolla", sub="cars")
        self.listing("Honda motorbike", sub="motorcycles")

        response = self.client.get(reverse("product_list"), {"category": "vehicles", "sub": "cars"})

        self.assertEqual([p.title for p in response.context["products"]], ["Toyota Corolla"])
        self.assertContains(response, "Motorcycles &amp; scooters")

    def test_numeric_and_choice_attribute_filters(self):
        self.listing("Old Corolla", sub="cars", attributes={"year": 2008, "make": "Toyota", "mileage": 210000})
        self.listing("New Corolla", sub="cars", attributes={"year": 2019, "make": "Toyota", "mileage": 40000})
        self.listing("New Civic", sub="cars", attributes={"year": 2020, "make": "Honda", "mileage": 30000})

        response = self.client.get(reverse("product_list"), {
            "category": "vehicles", "a_year_min": "2015", "a_make": "Toyota",
        })

        self.assertEqual([p.title for p in response.context["products"]], ["New Corolla"])
        self.assertContains(response, "Year of manufacture: from 2015")

    def test_boolean_attribute_filter(self):
        self.listing("Furnished flat", category="property", attributes={"listing_type": "For rent", "furnished": True})
        self.listing("Empty flat", category="property", attributes={"listing_type": "For rent", "furnished": False})

        response = self.client.get(reverse("product_list"), {"category": "property", "a_furnished": "yes"})

        self.assertEqual([p.title for p in response.context["products"]], ["Furnished flat"])

    def test_attribute_filters_are_ignored_without_category(self):
        self.listing("Old Corolla", attributes={"year": 2008})
        response = self.client.get(reverse("product_list"), {"a_year_min": "2015"})
        self.assertEqual(response.context["result_count"], 1)

    def test_invalid_choice_value_does_not_filter(self):
        self.listing("Corolla", sub="cars", attributes={"make": "Toyota"})
        response = self.client.get(reverse("product_list"), {"category": "vehicles", "a_make": "<script>"})
        self.assertEqual(response.context["result_count"], 1)


class SearchTests(CatalogFixtures):
    def test_every_search_word_must_match(self):
        self.listing("Toyota Corolla 2015", city="Tema")
        self.listing("Toyota Hilux", city="Kumasi")

        response = self.client.get(reverse("product_list"), {"q": "toyota tema"})

        self.assertEqual([p.title for p in response.context["products"]], ["Toyota Corolla 2015"])

    def test_relevance_puts_title_matches_first(self):
        self.listing("Phone case", category="phones-tech", description="Fits an iPhone 13.")
        self.listing("iPhone 13", category="phones-tech")

        response = self.client.get(reverse("product_list"), {"q": "iphone 13"})

        self.assertEqual(response.context["selected_sort"], "relevance")
        self.assertEqual(response.context["products"][0].title, "iPhone 13")

    def test_category_name_matches_search(self):
        self.listing("Two bedroom flat", category="property", sub="houses-for-rent")
        response = self.client.get(reverse("product_list"), {"q": "rent"})
        self.assertEqual(response.context["result_count"], 1)

    def test_successful_search_is_counted_for_popular_searches(self):
        self.listing("Toyota Corolla")
        self.client.get(reverse("product_list"), {"q": "  Toyota  "})
        self.client.get(reverse("product_list"), {"q": "toyota"})
        self.client.get(reverse("product_list"), {"q": "nothing matches"})

        self.assertEqual(SearchTerm.objects.get(term="toyota").hits, 2)
        self.assertFalse(SearchTerm.objects.filter(term="nothing matches").exists())
        self.assertContains(self.client.get(reverse("home")), "Popular Searches")

    def test_hidden_terms_are_not_shown(self):
        SearchTerm.objects.create(term="badword", hits=50, is_hidden=True)
        self.assertNotContains(self.client.get(reverse("home")), "badword")

    def test_suggestions_endpoint_returns_categories_and_titles(self):
        self.listing("Toyota Corolla")
        self.listing("Toyota Corolla", status=Product.Status.PENDING)

        data = self.client.get(reverse("search_suggestions"), {"q": "coro"}).json()

        self.assertEqual(data["listings"], ["Toyota Corolla"])
        data = self.client.get(reverse("search_suggestions"), {"q": "motor"}).json()
        self.assertIn("Cars & Vehicles › Motorcycles & scooters", [c["label"] for c in data["categories"]])

    def test_suggestions_ignore_short_queries(self):
        self.assertEqual(self.client.get(reverse("search_suggestions"), {"q": "a"}).json()["listings"], [])


class RecentlyViewedTests(CatalogFixtures):
    def test_viewed_listings_appear_on_home_most_recent_first(self):
        first, second = self.listing("First car"), self.listing("Second car")
        self.client.get(reverse("product_detail", args=[first.pk]))
        self.client.get(reverse("product_detail", args=[second.pk]))

        response = self.client.get(reverse("home"))

        self.assertEqual([p.title for p in response.context["recently_viewed"]], ["Second car", "First car"])

    def test_unpublished_listings_drop_out(self):
        product = self.listing("Car")
        self.client.get(reverse("product_detail", args=[product.pk]))
        Product.objects.filter(pk=product.pk).update(status=Product.Status.DRAFT)
        self.assertEqual(self.client.get(reverse("home")).context["recently_viewed"], [])


class CategoryListingFormTests(CatalogFixtures):
    def test_create_page_starts_with_category_picker(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("product_create"))
        self.assertTemplateUsed(response, "marketplace/category_picker.html")
        self.assertContains(response, "?category=vehicles&amp;sub=cars")

    def test_form_shows_category_specific_fields(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("product_create"), {"category": "vehicles", "sub": "cars"})
        self.assertContains(response, "Year of manufacture")
        self.assertContains(response, "Mileage (km)")
        self.assertNotContains(response, "Bedrooms")

    def test_listing_saves_typed_attributes(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create") + "?category=vehicles&sub=cars", {
            "title": "Toyota Corolla 2015", "category": "vehicles", "subcategory": Category.objects.get(slug="cars").pk,
            "condition": Product.Condition.GOOD, "price": "68000", "description": "Well maintained.",
            "region": GhanaRegion.GREATER_ACCRA, "city": "Tema", "images": [sample_product_image()],
            "attr_make": "Toyota", "attr_year": "2015", "attr_mileage": "120000", "attr_transmission": "Automatic",
        })

        product = Product.objects.get(title="Toyota Corolla 2015")
        self.assertRedirects(response, reverse("product_detail", args=[product.pk]))
        self.assertEqual(product.attributes, {
            "make": "Toyota", "year": 2015, "mileage": 120000, "transmission": "Automatic",
        })
        self.assertEqual(product.subcategory.slug, "cars")
        detail = self.client.get(reverse("product_detail", args=[product.pk]))
        self.assertContains(detail, "120,000 km")
        self.assertContains(detail, "<dd>2015</dd>")

    def test_required_attribute_is_enforced(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), {
            "title": "Flat", "category": "property", "condition": Product.Condition.GOOD, "price": "2000",
            "description": "Nice flat.", "region": GhanaRegion.GREATER_ACCRA, "city": "Accra",
            "images": [sample_product_image()],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Flat").exists())
        self.assertIn("attr_listing_type", response.context["form"].errors)

    def test_subcategory_from_another_category_is_rejected(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("product_create"), {
            "title": "Odd", "category": "fashion", "subcategory": Category.objects.get(slug="cars").pk,
            "condition": Product.Condition.GOOD, "price": "20", "description": "x",
            "region": GhanaRegion.GREATER_ACCRA, "city": "Accra", "images": [sample_product_image()],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="Odd").exists())

    def test_price_label_follows_category(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("product_create"), {"category": "jobs"})
        self.assertContains(response, "Monthly salary (GH₵)")

    def test_admin_added_attribute_appears_without_code_changes(self):
        CategoryAttribute.objects.create(
            category=Category.objects.get(slug="fashion"), key="material", label="Fabric", kind="text",
        )
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("product_create"), {"category": "fashion"}), "Fabric")


class AttributeHelpTextEscapingTests(CatalogFixtures):
    def test_admin_entered_help_text_is_escaped(self):
        CategoryAttribute.objects.create(
            category=Category.objects.get(slug="fashion"), key="fabric", label="Fabric", kind="text",
            help_text='<script>alert("x")</script>',
        )
        self.client.force_login(self.seller)
        response = self.client.get(reverse("product_create"), {"category": "fashion"})
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")


class BrowseFacetTests(CatalogFixtures):
    def test_make_tiles_show_counts_and_toggle(self):
        for make in ("Toyota", "Toyota", "Honda"):
            self.listing(f"{make} car", sub="cars", attributes={"make": make})

        response = self.client.get(reverse("product_list"), {"category": "vehicles"})

        options = response.context["facet"]["options"]
        self.assertEqual([(o["value"], o["count"]) for o in options], [("Toyota", 2), ("Honda", 1)])
        self.assertIn("a_make=Toyota", options[0]["url"])
        filtered = self.client.get(reverse("product_list"), {"category": "vehicles", "a_make": "Toyota"})
        self.assertEqual(filtered.context["result_count"], 2)
        self.assertTrue(filtered.context["facet"]["options"][0]["selected"])

    def test_quick_price_ranges_split_results(self):
        for price in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000):
            self.listing(f"Item {price}", category="fashion", price=price)

        buckets = self.client.get(reverse("product_list"), {"category": "fashion"}).context["quick_prices"]

        self.assertEqual(len(buckets), 4)
        self.assertEqual(buckets[0]["min"], "")
        self.assertEqual(buckets[-1]["max"], "")
        self.assertTrue(buckets[0]["label"].startswith("Under GH₵"))

    def test_no_price_ranges_for_tiny_result_sets(self):
        self.listing("Only item", category="fashion")
        self.assertEqual(self.client.get(reverse("product_list"), {"category": "fashion"}).context["quick_prices"], [])
