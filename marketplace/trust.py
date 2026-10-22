"""Trust and safety helpers: listing risk checks, seller ratings and account deletion."""
import re
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from .models import Favorite, Product, ProhibitedTerm, SellerReview

DUPLICATE_LOOKBACK_DAYS = 14


def _normalise(text):
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _matching_terms(text):
    haystack = f" {_normalise(text)} "
    for term in ProhibitedTerm.objects.filter(is_active=True):
        needle = _normalise(term.term)
        if needle and f" {needle} " in haystack:
            yield term


def blocked_listing_reason(title, description, brand="", model=""):
    """Return a seller-facing reason when the listing uses a blocked term, otherwise None."""
    text = " ".join((title, description, brand, model))
    for term in _matching_terms(text):
        if term.action == ProhibitedTerm.Action.BLOCK:
            return term.reason or "This item is not allowed on GhanaMarket. See our prohibited items list."
    return None


def listing_risk_flags(product):
    """Moderator hints for a listing about to be (re)submitted. Never shown to buyers."""
    flags = []
    text = " ".join((product.title, product.description, product.brand, product.model))
    flagged = [t.term for t in _matching_terms(text) if t.action == ProhibitedTerm.Action.FLAG]
    if flagged:
        flags.append("Flagged words: " + ", ".join(flagged))
    if product.category.is_restricted or (product.subcategory_id and product.subcategory.is_restricted):
        flags.append("Restricted category")
    recent = timezone.now() - timedelta(days=DUPLICATE_LOOKBACK_DAYS)
    others = Product.objects.exclude(pk=product.pk).exclude(status=Product.Status.REJECTED).filter(
        title__iexact=product.title.strip()
    )
    if others.filter(seller=product.seller).exists():
        flags.append("Possible duplicate of this seller's listing")
    if others.exclude(seller=product.seller).filter(price=product.price, created_at__gte=recent).exists():
        flags.append("Same title and price as another seller's recent listing")
    if not Product.objects.filter(seller=product.seller, status=Product.Status.PUBLISHED).exclude(pk=product.pk).exists():
        flags.append("Seller's first listing")
    return "; ".join(flags)[:500]


def seller_rating(seller):
    """{'average': 4.6, 'count': 12} from visible reviews, or None when nothing has been earned yet."""
    stats = SellerReview.objects.filter(seller=seller, is_hidden=False).aggregate(average=Avg("rating"), count=Count("id"))
    if not stats["count"]:
        return None
    return {"average": round(stats["average"], 1), "count": stats["count"]}


def can_review(order, user):
    from commerce.models import Order

    return (
        order.buyer_id == user.pk and order.status == Order.Status.COMPLETED
        and not SellerReview.objects.filter(order=order).exists()
    )


class AccountDeletionBlocked(Exception):
    pass


@transaction.atomic
def delete_account(user):
    """Anonymise an account. Order records are kept (financial record-keeping) without contact details."""
    from commerce.models import Address, CartItem, Order

    open_sales = Order.objects.filter(seller=user, status__in=(
        Order.Status.PAID, Order.Status.PROCESSING, Order.Status.SHIPPED, Order.Status.READY_FOR_PICKUP,
    ))
    open_purchases = Order.objects.filter(buyer=user, status__in=(
        Order.Status.PAID, Order.Status.PROCESSING, Order.Status.SHIPPED, Order.Status.READY_FOR_PICKUP,
    ))
    if open_sales.exists() or open_purchases.exists():
        raise AccountDeletionBlocked("Finish or cancel your open orders before deleting your account.")
    Product.objects.filter(seller=user).exclude(status=Product.Status.SOLD).update(status=Product.Status.DRAFT)
    Favorite.objects.filter(user=user).delete()
    CartItem.objects.filter(user=user).delete()
    Address.objects.filter(user=user).delete()
    user.notifications.all().delete()
    Order.objects.filter(buyer=user).update(recipient_name="", recipient_phone="", delivery_address="", buyer_note="")
    user.username = f"deleted-{user.pk}"
    user.email = f"deleted-{user.pk}@deleted.invalid"
    user.first_name = user.last_name = user.phone_number = user.city = ""
    user.region = ""
    user.is_active = False
    user.deleted_at = timezone.now()
    user.password = make_password(None)
    user.save()
