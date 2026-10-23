from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import GhanaRegion, Notification, Product, SellerVerification, User

PASSWORD = "A-strong-password-482!"


class SellerApprovalFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.buyer = User.objects.create_user("kofi", "kofi@example.com", PASSWORD, phone_number="0240000000",
                                              city="Accra", region=GhanaRegion.GREATER_ACCRA)

    def test_pending_seller_cannot_post_until_approved(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("become_seller"), {
            "phone_number": "0240000000", "city": "Accra", "region": GhanaRegion.GREATER_ACCRA,
        })
        response = self.client.get(reverse("product_create"), follow=True)
        self.assertRedirects(response, reverse("seller_listings"))
        self.assertContains(response, "Add your Ghana Card to finish your application")

    def test_existing_sellers_are_approved_by_default(self):
        seller = User.objects.create_user("old", "old@example.com", PASSWORD, role=User.Role.SELLER)
        self.assertTrue(seller.can_sell)

    def test_rejected_seller_sees_note_and_can_apply_again(self):
        self.buyer.request_seller_approval()
        self.buyer.seller_status = User.SellerStatus.REJECTED
        self.buyer.seller_review_note = "Please add a real phone number."
        self.buyer.save()
        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse("seller_listings")), "Please add a real phone number.")
        self.assertEqual(self.client.get(reverse("become_seller")).status_code, 200)


class ReviewCentreTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.applicant = User.objects.create_user("ama", "ama@example.com", PASSWORD, first_name="Ama",
                                                  phone_number="0241234567", city="Kumasi", region=GhanaRegion.ASHANTI)
        self.applicant.request_seller_approval()
        self.applicant.save()
        SellerVerification.objects.create(user=self.applicant, kind="ghana_card", legal_name="Ama Mensah",
                                          document_number="GHA-123456789-0", document="verifications/a.pdf")
        self.seller = User.objects.create_user("kojo", "kojo@example.com", PASSWORD, role=User.Role.SELLER)
        self.listing = Product.objects.create(
            seller=self.seller, title="Blender", description="Works well", category_id="home-living", price="250",
            city="Accra", status=Product.Status.PENDING, risk_flags="Seller's first listing",
        )
        self.url = reverse("marketplace_review_centre")
        self.client.force_login(self.admin)

    def decide(self, kind, pk, decision, note=""):
        return self.client.post(self.url, {"kind": kind, "pk": pk, "decision": decision, "note": note}, follow=True)

    def test_side_panel_shows_details_and_checklist(self):
        response = self.client.get(self.url, {"tab": "sellers"})
        self.assertContains(response, "0241234567")
        self.assertContains(response, "Before approving, confirm you checked")
        response = self.client.get(self.url, {"tab": "listings", "item": self.listing.pk})
        self.assertContains(response, "Works well")
        self.assertContains(response, "Seller&#x27;s first listing")

    def test_approving_a_seller_lets_them_post_and_notifies_them(self):
        response = self.decide("sellers", self.applicant.pk, "approve")
        self.assertContains(response, "approved")
        self.applicant.refresh_from_db()
        self.assertTrue(self.applicant.can_sell)
        self.assertTrue(Notification.objects.filter(user=self.applicant, title="You can start selling").exists())
        self.assertTrue(LogEntry.objects.filter(change_message="Seller request approved.").exists())

    def test_rejecting_needs_a_note(self):
        response = self.decide("sellers", self.applicant.pk, "reject")
        self.assertContains(response, "Write a short note")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.seller_status, User.SellerStatus.PENDING)

        self.decide("sellers", self.applicant.pk, "reject", "Phone number does not work")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.seller_status, User.SellerStatus.REJECTED)
        self.assertEqual(self.applicant.seller_review_note, "Phone number does not work")

    def test_listing_approval_and_return(self):
        self.decide("listings", self.listing.pk, "approve")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Product.Status.PUBLISHED)
        self.assertTrue(Notification.objects.filter(user=self.seller, title="Your ad is live").exists())

        other = Product.objects.create(seller=self.seller, title="Kettle", description="x", category_id="home-living",
                                       price="50", city="Accra", status=Product.Status.PENDING)
        self.decide("listings", other.pk, "reject", "Add a photo of the actual kettle")
        other.refresh_from_db()
        self.assertEqual(other.status, Product.Status.REJECTED)

    def test_listing_from_unapproved_seller_cannot_be_approved(self):
        Product.objects.filter(pk=self.listing.pk).update(seller=self.applicant)
        response = self.decide("listings", self.listing.pk, "approve")
        self.assertContains(response, "Approve the seller")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Product.Status.PENDING)

    def test_verification_badge_decision(self):
        verification = SellerVerification.objects.create(
            user=self.seller, kind="ghana_card", legal_name="Kojo Mensah", document_number="GHA-1",
            document="verifications/x.pdf",
        )
        self.decide("verifications", verification.pk, "approve")
        self.seller.refresh_from_db()
        self.assertTrue(self.seller.is_verified_seller)

    def test_already_decided_item_is_handled(self):
        self.decide("sellers", self.applicant.pk, "approve")
        response = self.decide("sellers", self.applicant.pk, "approve")
        self.assertContains(response, "already decided")

    def test_view_only_staff_cannot_decide(self):
        staff = User.objects.create_user("viewer", "v@example.com", PASSWORD, is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_user"))
        self.client.force_login(staff)
        page = self.client.get(self.url)
        self.assertContains(page, "cannot approve or reject")
        self.assertEqual(self.client.post(self.url, {"kind": "sellers", "pk": self.applicant.pk,
                                                     "decision": "approve"}).status_code, 403)
        self.applicant.refresh_from_db()
        self.assertFalse(self.applicant.can_sell)

    def test_non_staff_are_sent_to_login(self):
        self.client.force_login(self.applicant)
        self.assertEqual(self.client.get(self.url).status_code, 302)


class ReviewCentreChromeTests(ReviewCentreTests):
    def test_page_has_full_admin_sidebar_and_search(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context["cc_sidebar"])
        self.assertTrue(response.context["cc_can_search"])
        self.assertEqual(response.context["cc_review_total"], 3)  # seller request, listing, Ghana Card
        self.assertContains(response, 'href="/admin/review/"')
