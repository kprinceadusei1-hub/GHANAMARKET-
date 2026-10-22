from django.core.management.base import BaseCommand

from marketplace.category_catalog import seed_catalog
from marketplace.models import Category, CategoryAttribute


class Command(BaseCommand):
    help = "Create any missing launch categories, subcategories and attributes. Existing rows are not changed."

    def handle(self, *args, **options):
        created = seed_catalog(Category, CategoryAttribute)
        self.stdout.write(self.style.SUCCESS(f"Created {created} missing category rows."))
