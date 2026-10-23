from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import GhanaRegion, Notification, SellerVerification, User
from .review_centre import id_check

PASSWORD = "A-strong-password-482!"


def card(user, number="GHA-123456789-0", name="Ama Mensah", **extra):
    return SellerVerification.objects.create(user=user, kind="ghana_card", legal_name=name,
                                             document_number=number, document="verifications/a.jpg", **extra)


class VerificationDeskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.ama = User.objects.create_user("ama", "ama@example.com", PASSWORD, first_name="Ama", last_name="Mensah",
                                            phone_number="0241234567", city="Kumasi", region=GhanaRegion.ASHANTI)
        self.ama.request_seller_approval()
        self.ama.save()
        self.url = reverse("marketplace_review_centre")

    def levels(self, check):
        return {text: level for level, text in check["signals"]}

    def test_good_card_has_no_warnings(self):
        check = id_check(card(self.ama))
        self.assertEqual(check["warnings"], 0, check["signals"])
        self.assertTrue(check["is_image"])

    def test_warns_about_reused_number_wrong_name_and_bad_format(self):
        other = User.objects.create_user("kofi", "kofi@example.com", PASSWORD)
        card(other, name="Kofi Boateng")
        check = id_check(card(self.ama, name="Yaw Owusu"))
        signals = self.levels(check)
        self.assertEqual(signals["Same card number already used by @kofi"], "bad")
        self.assertIn("bad", [level for text, level in signals.items() if text.startswith("Name on card differs")])
        bad_format = id_check(card(self.ama, number="12345"))
        self.assertIn("Card number is not in the GHA-123456789-0 format", self.levels(bad_format))

    def test_card_photo_and_checks_show_in_seller_request(self):
        card(self.ama)
        self.client.force_login(self.admin)
        response = self.client.get(self.url, {"tab": "sellers"})
        self.assertContains(response, "GHA-123456789-0")
        self.assertContains(response, "Card number is not used by any other account")
        self.assertContains(response, "Also give the Verified ID badge")
        self.assertContains(response, reverse("verification_document", args=[self.ama.verifications.get().pk]))

    def test_approve_seller_and_badge_in_one_step(self):
        card(self.ama)
        self.client.force_login(self.admin)
        self.client.post(self.url, {"kind": "sellers", "pk": self.ama.pk, "decision": "approve", "also_verify": "1"})
        self.ama.refresh_from_db()
        self.assertTrue(self.ama.can_sell)
        self.assertTrue(self.ama.is_verified_seller)
        self.assertTrue(Notification.objects.filter(user=self.ama, title__contains="verified seller").exists())

    def test_without_the_tick_only_the_seller_is_approved(self):
        card(self.ama)
        self.client.force_login(self.admin)
        self.client.post(self.url, {"kind": "sellers", "pk": self.ama.pk, "decision": "approve"})
        self.ama.refresh_from_db()
        self.assertTrue(self.ama.can_sell)
        self.assertFalse(self.ama.is_verified_seller)
        self.assertEqual(self.ama.verifications.get().status, SellerVerification.Status.PENDING)

    def test_seller_without_card_shows_warning(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url, {"tab": "sellers"}), "No Ghana Card submitted yet")
