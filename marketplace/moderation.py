"""Approval decisions for listings, seller requests and seller verification.

Every decision is checked, recorded in Django's admin audit log and sent to the person as a
notification. Used by the Review Centre and the regular admin pages.
"""
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from .models import Product, SellerVerification, User
from .notifications import notify


class ModerationError(Exception):
    """The decision is not allowed for the item's current state; the message is safe to show."""


def _log(staff, obj, message):
    LogEntry.objects.log_action(
        user_id=staff.pk, content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk, object_repr=str(obj)[:200], action_flag=CHANGE, change_message=message,
    )


def _require_note(note):
    note = (note or "").strip()
    if not note:
        raise ModerationError("Write a short note telling the person what to fix.")
    return note[:300]


# ---------------------------------------------------------------- listings

def approve_listing(product, staff):
    if product.status != Product.Status.PENDING or product.is_demo:
        raise ModerationError("Only a real listing awaiting review can be approved.")
    if not product.seller.can_sell:
        raise ModerationError("Approve the seller's account first, then the listing.")
    product.status = Product.Status.PUBLISHED
    product.moderation_note = ""
    product.save(update_fields=("status", "moderation_note", "updated_at"))
    _log(staff, product, "Listing approved and published after individual review.")
    notify(product.seller, "Your ad is live", f"“{product.title}” is now visible to buyers.",
           reverse("product_detail", args=[product.pk]))


def return_listing(product, staff, note):
    if product.status != Product.Status.PENDING or product.is_demo:
        raise ModerationError("Only a real listing awaiting review can be returned for changes.")
    note = _require_note(note)
    product.status = Product.Status.REJECTED
    product.moderation_note = note
    product.save(update_fields=("status", "moderation_note", "updated_at"))
    _log(staff, product, f"Listing returned to seller: {note}")
    notify(product.seller, "Your ad needs changes", f"“{product.title}”: {note}", reverse("seller_listings"))


# ---------------------------------------------------------------- seller requests

def approve_seller(user, staff):
    if user.role != User.Role.SELLER or user.seller_status != User.SellerStatus.PENDING:
        raise ModerationError("This account has no seller request waiting for review.")
    user.seller_status = User.SellerStatus.APPROVED
    user.seller_review_note = ""
    user.save(update_fields=("seller_status", "seller_review_note"))
    _log(staff, user, "Seller request approved.")
    notify(user, "You can start selling", "Your seller account was approved. Post your first ad now.",
           reverse("product_create"))


def reject_seller(user, staff, note):
    if user.role != User.Role.SELLER or user.seller_status != User.SellerStatus.PENDING:
        raise ModerationError("This account has no seller request waiting for review.")
    note = _require_note(note)
    user.seller_status = User.SellerStatus.REJECTED
    user.seller_review_note = note
    user.save(update_fields=("seller_status", "seller_review_note"))
    _log(staff, user, f"Seller request not approved: {note}")
    notify(user, "Seller request not approved", note, reverse("seller_listings"))


# ---------------------------------------------------------------- verification badge

def _sync_verified_at(user):
    approved = user.verifications.filter(status=SellerVerification.Status.APPROVED).order_by("reviewed_at").last()
    user.verified_at = approved.reviewed_at if approved else None
    user.save(update_fields=("verified_at",))


def decide_verification(verification, staff, approve, note=""):
    if approve:
        verification.reviewer_note = ""
    else:
        verification.reviewer_note = _require_note(note or verification.reviewer_note)
    verification.status = SellerVerification.Status.APPROVED if approve else SellerVerification.Status.REJECTED
    verification.reviewed_by = staff
    verification.reviewed_at = timezone.now()
    verification.save()
    _sync_verified_at(verification.user)
    _log(staff, verification, f"Verification {verification.status}" + ("" if approve else f": {verification.reviewer_note}"))
    if approve:
        notify(verification.user, "You are now a verified seller",
               "The badge now shows on your listings and storefront.", reverse("seller_verification"))
    else:
        notify(verification.user, "Verification not approved", verification.reviewer_note,
               reverse("seller_verification"))
