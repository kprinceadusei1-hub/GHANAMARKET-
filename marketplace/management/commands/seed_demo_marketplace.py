from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from marketplace.models import GhanaRegion, Product, User


DEMO_LISTINGS = (
    {
        "title": "Samsung Galaxy A55 128GB",
        "category": Product.Category.PHONES_TECH,
        "condition": Product.Condition.NEW,
        "price": "3200.00",
        "city": "Accra",
        "description": "A preview example of a new mid-range smartphone listing with 128 GB storage.",
    },
    {
        "title": "HP Pavilion Laptop Core i5, 8GB RAM",
        "category": "electronics",
        "condition": Product.Condition.GOOD,
        "price": "2800.00",
        "city": "Tema",
        "description": "A preview example of a used laptop listing: Intel Core i5 processor and 8 GB RAM.",
    },
    {
        "title": "Nike Air Force 1 Men's Sneakers",
        "category": Product.Category.FASHION,
        "condition": Product.Condition.NEW,
        "price": "650.00",
        "city": "Accra",
        "description": "A preview example of a new pair of men's sneakers.",
    },
    {
        "title": "3 Bedroom House for Sale - East Legon",
        "category": Product.Category.PROPERTY,
        "condition": Product.Condition.GOOD,
        "price": "1200000.00",
        "city": "Accra",
        "attributes": {"listing_type": "For sale", "bedrooms": 3},
        "description": "A preview example of a property-for-sale listing. Details are illustrative only.",
    },
    {
        "title": "Samsung Galaxy A15 · 128 GB",
        "category": Product.Category.PHONES_TECH,
        "condition": Product.Condition.LIKE_NEW,
        "price": "2450.00",
        "city": "Accra",
        "description": "A preview example of a popular everyday smartphone, with a bright display and room for your photos and apps.",
    },
    {
        "title": "Handwoven Kente Tote",
        "category": Product.Category.FASHION,
        "condition": Product.Condition.NEW,
        "price": "180.00",
        "city": "Kumasi",
        "description": "A preview example inspired by Ghanaian woven textiles. A roomy carry-all for market trips and everyday errands.",
    },
    {
        "title": "Carved Hardwood Accent Stool",
        "category": Product.Category.HOME_LIVING,
        "condition": Product.Condition.NEW,
        "price": "320.00",
        "city": "Accra",
        "description": "A preview example of a hand-finished hardwood accent stool for a living room, bedroom or entryway.",
    },
    {
        "title": "Classic Leather Crossbody",
        "category": Product.Category.FASHION,
        "condition": Product.Condition.GOOD,
        "price": "260.00",
        "city": "Tema",
        "description": "A preview example of a compact crossbody bag with an adjustable strap and space for daily essentials.",
    },
    {
        "title": "Wireless Headphones",
        "category": Product.Category.PHONES_TECH,
        "condition": Product.Condition.LIKE_NEW,
        "price": "590.00",
        "city": "Accra",
        "description": "A preview example of over-ear wireless headphones for music, calls and commuting.",
    },
    {
        "title": "Handmade Ceramic Serving Set",
        "category": Product.Category.HOME_LIVING,
        "condition": Product.Condition.NEW,
        "price": "450.00",
        "city": "Cape Coast",
        "description": "A preview example of a small locally inspired ceramic serving set for a kitchen or dining table.",
    },
    {
        "title": "City Commuter Bicycle",
        "category": Product.Category.VEHICLES,
        "condition": Product.Condition.GOOD,
        "price": "1350.00",
        "city": "Tema",
        "description": "A preview example of a practical city bicycle for short commutes and weekend rides.",
    },
    {
        "title": "Used Toyota Corolla · 2015",
        "category": Product.Category.VEHICLES,
        "condition": Product.Condition.GOOD,
        "price": "68000.00",
        "city": "Tema",
        "description": "A preview example of a used compact sedan listing. Vehicle details and availability are illustrative only.",
    },
    {
        "title": "Compact Two-Burner Gas Cooker",
        "category": Product.Category.HOME_LIVING,
        "condition": Product.Condition.GOOD,
        "price": "780.00",
        "city": "Kumasi",
        "description": "A preview example of a compact two-burner cooker suited to a small kitchen or student flat.",
    },
    {
        "title": "Solid Wood Writing Desk",
        "category": Product.Category.HOME_LIVING,
        "condition": Product.Condition.GOOD,
        "price": "980.00",
        "city": "Accra",
        "description": "A preview example of a sturdy writing desk with a simple finish for a home office or study corner.",
    },
    {
        "title": "Canon EOS M50 Camera Kit",
        "category": Product.Category.PHONES_TECH,
        "condition": Product.Condition.GOOD,
        "price": "5800.00",
        "city": "Accra",
        "description": "A preview example of a compact mirrorless camera kit for travel, portraits and video.",
    },
    {
        "title": "Handmade Beaded Sandals",
        "category": Product.Category.FASHION,
        "condition": Product.Condition.NEW,
        "price": "160.00",
        "city": "Kumasi",
        "description": "A preview example inspired by handmade beadwork and designed for everyday casual wear.",
    },
    {
        "title": "Two-Bedroom Apartment · East Legon",
        "category": Product.Category.PROPERTY,
        "condition": Product.Condition.GOOD,
        "price": "4500.00",
        "city": "Accra",
        "description": "A preview example of a monthly rental listing. Availability and details are illustrative only.",
    },
)

DEMO_PHOTOS = {
    "Samsung Galaxy A55 128GB": "marketplace/static/marketplace/demo/photos/samsung-galaxy-a55.jpg",
    "HP Pavilion Laptop Core i5, 8GB RAM": "marketplace/static/marketplace/demo/photos/hp-pavilion-laptop.jpg",
    "Nike Air Force 1 Men's Sneakers": "marketplace/static/marketplace/demo/photos/nike-air-force-1.jpg",
    "3 Bedroom House for Sale - East Legon": "marketplace/static/marketplace/demo/photos/three-bedroom-house.jpg",
    "Samsung Galaxy A15 · 128 GB": "marketplace/static/marketplace/demo/photos/smartphone-display.jpg",
    "Handwoven Kente Tote": "marketplace/static/marketplace/demo/photos/kente-cloth.jpg",
    "Carved Hardwood Accent Stool": "marketplace/static/marketplace/demo/photos/ghana-stool.jpg",
    "Classic Leather Crossbody": "marketplace/static/marketplace/demo/photos/leather-handbag.jpg",
    "Wireless Headphones": "marketplace/static/marketplace/demo/photos/wireless-headphones.jpg",
    "Handmade Ceramic Serving Set": "marketplace/static/marketplace/demo/photos/ceramic-plate.jpg",
    "City Commuter Bicycle": "marketplace/static/marketplace/demo/photos/city-bicycle.jpg",
    "Used Toyota Corolla · 2015": "marketplace/static/marketplace/demo/photos/corolla.jpg",
    "Compact Two-Burner Gas Cooker": "marketplace/static/marketplace/demo/photos/gas-stove.jpg",
    "Solid Wood Writing Desk": "marketplace/static/marketplace/demo/photos/writing-desk.jpg",
    "Canon EOS M50 Camera Kit": "marketplace/static/marketplace/demo/photos/canon-camera.jpg",
    "Handmade Beaded Sandals": "marketplace/static/marketplace/demo/photos/kete-dancer.jpg",
    "Two-Bedroom Apartment · East Legon": "marketplace/static/marketplace/demo/photos/apartment-interior.jpg",
}

REGION_BY_CITY = {
    "Accra": GhanaRegion.GREATER_ACCRA,
    "Cape Coast": GhanaRegion.CENTRAL,
    "Kumasi": GhanaRegion.ASHANTI,
    "Tema": GhanaRegion.GREATER_ACCRA,
}


class Command(BaseCommand):
    help = "Create clearly marked preview listings with representative photographs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete", action="store_true",
            help="Permanently delete every preview listing, its photos and the preview seller account.",
        )

    def handle(self, *args, **options):
        if options["delete"]:
            return self.delete_previews()
        user_model = get_user_model()
        seller, created = user_model.objects.get_or_create(
            username="marketplace-preview-seller",
            defaults={
                "email": "marketplace-preview-seller@example.invalid",
                "first_name": "Marketplace",
                "last_name": "Preview Shop",
                "role": User.Role.SELLER,
                "city": "Accra",
                "region": GhanaRegion.GREATER_ACCRA,
                "country": settings.DEFAULT_COUNTRY,
            },
        )
        if not created and (
            seller.email != "marketplace-preview-seller@example.invalid"
            or seller.role != User.Role.SELLER
            or seller.has_usable_password()
        ):
            raise CommandError(
                "The reserved preview seller username is already used by a non-demo account."
            )
        if created:
            seller.set_unusable_password()
            seller.save(update_fields=("password",))
        if seller.region != GhanaRegion.GREATER_ACCRA:
            seller.region = GhanaRegion.GREATER_ACCRA
            seller.save(update_fields=("region",))

        for listing in reversed(DEMO_LISTINGS):
            slug = slugify(listing["title"])
            image_name = f"demo/{slug}.jpg"
            if default_storage.exists(image_name):
                default_storage.delete(image_name)
            photo_path = settings.BASE_DIR / DEMO_PHOTOS[listing["title"]]
            image_name = default_storage.save(
                image_name,
                ContentFile(photo_path.read_bytes()),
            )
            legacy_image = f"demo/{slug}.svg"
            if default_storage.exists(legacy_image):
                default_storage.delete(legacy_image)
            Product.objects.update_or_create(
                seller=seller,
                title=listing["title"],
                defaults={
                    "description": (
                        "DEMO PREVIEW ONLY: This sample listing, its details and its "
                        "price are illustrative and are not a real product or offer.\n\n"
                        f"{listing['description']}"
                    ),
                    "category_id": listing["category"],
                    "condition": listing["condition"],
                    "price": listing["price"],
                    "currency": settings.DEFAULT_CURRENCY,
                    "city": listing["city"],
                    "region": REGION_BY_CITY[listing["city"]],
                    "country": settings.DEFAULT_COUNTRY,
                    "status": Product.Status.PUBLISHED,
                    "is_demo": True,
                    "image": image_name,
                    "attributes": listing.get("attributes", {}),
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(DEMO_LISTINGS)} preview listings with representative photos. "
                "They are not real products or offers."
            )
        )

    def delete_previews(self):
        count = delete_preview_catalogue()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} preview listings and the preview seller."))


def delete_preview_catalogue():
    """Permanently remove every preview listing, its photos and the preview seller. Returns the count."""
    previews = Product.objects.filter(is_demo=True)
    count = previews.count()
    for product in previews:
        files = [photo.image for photo in product.photos.all()]
        if product.image:
            files.append(product.image)
        product.delete()
        for image in files:
            image.delete(save=False)
    get_user_model().objects.filter(
        username="marketplace-preview-seller", email="marketplace-preview-seller@example.invalid",
    ).delete()
    return count
