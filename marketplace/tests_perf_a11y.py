"""Regression tests for the performance and accessibility audit fixes."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import GhanaRegion, Product, User

PASSWORD = "A-strong-password-482!"


class SellerDashboardQueryTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", "s@example.com", PASSWORD, role=User.Role.SELLER)
        self.client.force_login(self.seller)

    def add(self, count):
        Product.objects.bulk_create(Product(
            seller=self.seller, title=f"Item {i}", description="x", category_id="phones-tech", price="10",
            city="Accra", region=GhanaRegion.GREATER_ACCRA, status=Product.Status.PUBLISHED) for i in range(count))

    def queries(self):
        self.client.get(reverse("seller_listings"))  # warm caches
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("seller_listings"))
        return len(captured)

    def test_query_count_does_not_grow_with_listings(self):
        self.add(3)
        few = self.queries()
        self.add(20)
        self.assertEqual(self.queries(), few)

    def test_dashboard_is_paginated(self):
        self.add(30)
        response = self.client.get(reverse("seller_listings"))
        self.assertEqual(len(response.context["products"]), 24)
        self.assertContains(response, "Page <strong>1</strong> of 2")


class FormErrorAccessibilityTests(TestCase):
    def test_invalid_field_points_to_its_error(self):
        response = self.client.post(reverse("register"), {"username": "", "email": "not-an-email"})
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="id_email_errors"')
        self.assertContains(response, "id_email_errors")
