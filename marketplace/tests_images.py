import io

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .images import MAX_DIMENSION, thumbnail_url
from .models import GhanaRegion, Product, User

GPS_IFD = 0x8825


def photo_with_gps(size=(3000, 2000), fmt="JPEG"):
    image = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[GPS_IFD] = {1: "N", 2: (5.0, 36.0, 0.0), 3: "W", 4: (0.0, 11.0, 0.0)}  # Accra
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, exif=exif)
    return buffer.getvalue()


class ImagePipelineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user(
            "seller", "seller@example.com", "A-strong-password-482!", role=User.Role.SELLER,
            phone_number="024", city="Accra", region=GhanaRegion.GREATER_ACCRA,
        )

    def post_listing(self, data, name="photo.jpg", content_type="image/jpeg"):
        self.client.force_login(self.seller)
        return self.client.post(reverse("product_create"), {
            "title": "Lamp", "category": "home-living", "condition": "good", "price": "50",
            "description": "Desk lamp.", "region": GhanaRegion.GREATER_ACCRA, "city": "Accra",
            "images": [SimpleUploadedFile(name, data, content_type=content_type)],
        })

    def test_uploads_lose_gps_metadata_and_are_resized(self):
        original = photo_with_gps()
        with Image.open(io.BytesIO(original)) as check:
            self.assertIn(GPS_IFD, check.getexif())  # the fixture really carries location data
        self.post_listing(original)
        product = Product.objects.get(title="Lamp")
        with default_storage.open(product.image.name, "rb") as handle, Image.open(handle) as stored:
            self.assertEqual(stored.format, "JPEG")
            self.assertLessEqual(max(stored.size), MAX_DIMENSION)
            exif = stored.getexif()
            self.assertNotIn(GPS_IFD, exif)
            self.assertNotIn(0x010F, exif)
        self.assertLess(product.image.size, len(original))

    def test_png_with_transparency_becomes_jpeg(self):
        image = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.post_listing(buffer.getvalue(), name="logo.png", content_type="image/png")
        self.assertTrue(Product.objects.get(title="Lamp").image.name.endswith(".jpg"))

    def test_thumbnail_is_generated_once_and_small(self):
        self.post_listing(photo_with_gps())
        product = Product.objects.get(title="Lamp")
        url = thumbnail_url(product.image, 480)
        self.assertIn("/thumbs/480/", url)
        thumb_name = url.split(default_storage.base_url, 1)[1]
        with default_storage.open(thumb_name, "rb") as handle, Image.open(handle) as thumb:
            self.assertEqual(thumb.width, 480)
        self.assertEqual(thumbnail_url(product.image, 480), url)

    def test_missing_original_falls_back_without_error(self):
        product = Product.objects.create(
            seller=self.seller, title="Ghost", description="x", category_id="other", price="1", city="Accra",
            image="products/does-not-exist.jpg", status=Product.Status.PUBLISHED,
        )
        self.assertTrue(thumbnail_url(product.image, 480).endswith("does-not-exist.jpg"))
        self.assertEqual(self.client.get(reverse("product_list")).status_code, 200)
