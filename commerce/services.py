"""Business rules for carts, checkout, payment confirmation, order status and refunds.

Views call these functions; they never change order or payment state directly. Every state change
runs in a transaction with row locks so concurrent requests (e.g. a webhook and a browser
callback arriving together) cannot double-process a payment or oversell stock.
"""
import logging
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.urls import reverse
from django.utils import timezone

from marketplace.models import Product, User
from marketplace.notifications import notify
from marketplace.templatetags.market import cedis

from .models import CartItem, Checkout, Order, OrderEvent, OrderItem, Payment, Refund
from .payments import PaymentError

logger = logging.getLogger(__name__)
MAX_QUANTITY_PER_ITEM = 20
# A checkout with a payment still in progress is kept open this long past its expiry, so a Mobile
# Money approval that lands at the last minute is not cancelled under the buyer.
PAYMENT_GRACE_MINUTES = 30


class CommerceError(Exception):
    """A user-facing rule violation; the message is safe to show."""


# ---------------------------------------------------------------- cart

def add_to_cart(user, product, quantity=1):
    if product.seller_id == user.pk:
        raise CommerceError("You cannot buy your own listing.")
    if not product.can_checkout:
        raise CommerceError("This item is not available for online checkout. Message the seller instead.")
    if User.blocked_between(user, product.seller):
        raise CommerceError("You cannot buy from this seller.")
    item, created = CartItem.objects.get_or_create(user=user, product=product, defaults={"quantity": 0})
    new_quantity = item.quantity + quantity
    if new_quantity > product.stock_quantity:
        raise CommerceError(f"Only {product.stock_quantity} available.")
    item.quantity = min(new_quantity, MAX_QUANTITY_PER_ITEM)
    item.save(update_fields=("quantity",))
    return item


def set_cart_quantity(item, quantity):
    if quantity <= 0:
        item.delete()
        return None
    if quantity > item.product.stock_quantity:
        raise CommerceError(f"Only {item.product.stock_quantity} of “{item.product.title}” available.")
    item.quantity = min(quantity, MAX_QUANTITY_PER_ITEM)
    item.save(update_fields=("quantity",))
    return item


def cart_groups(user):
    """Cart lines grouped by seller: [{'seller', 'items', 'subtotal', 'problems'}]."""
    groups = OrderedDict()
    items = CartItem.objects.filter(user=user).select_related("product__seller", "product__category")
    for item in items:
        product = item.product
        group = groups.setdefault(product.seller_id, {
            "seller": product.seller, "items": [], "subtotal": Decimal("0"), "problems": [],
        })
        problem = ""
        if not product.can_checkout:
            problem = "No longer available for online checkout."
        elif item.quantity > product.stock_quantity:
            problem = f"Only {product.stock_quantity} left."
        group["items"].append({"item": item, "problem": problem})
        if problem:
            group["problems"].append(problem)
        else:
            group["subtotal"] += item.line_total
    return list(groups.values())


def cart_count(user):
    return CartItem.objects.filter(user=user).aggregate(total=Sum("quantity"))["total"] or 0


# ---------------------------------------------------------------- checkout

@transaction.atomic
def create_checkout(user, delivery_by_seller, address=None, note=""):
    """Turn the cart into a pending checkout with one order per seller, reserving stock.

    ``delivery_by_seller`` maps seller id -> DeliveryOption chosen for that seller's items.
    """
    items = list(
        CartItem.objects.filter(user=user).select_related("product").order_by("product__seller_id", "pk")
    )
    if not items:
        raise CommerceError("Your cart is empty.")
    # Lock the product rows so two buyers cannot both take the last unit.
    products = {p.pk: p for p in Product.objects.select_for_update().select_related("category").filter(
        pk__in=[i.product_id for i in items])}
    by_seller = OrderedDict()
    for item in items:
        product = products[item.product_id]
        if not product.can_checkout:
            raise CommerceError(f"“{product.title}” is no longer available for online checkout.")
        if User.blocked_between(user, product.seller):
            raise CommerceError(f"“{product.title}” cannot be bought from this seller. Remove it from your cart.")
        if item.quantity > product.stock_quantity:
            raise CommerceError(f"Only {product.stock_quantity} of “{product.title}” left. Update your cart.")
        by_seller.setdefault(product.seller_id, []).append((product, item.quantity))

    needs_address = False
    for seller_id in by_seller:
        option = delivery_by_seller.get(seller_id)
        if option is None or not option.is_active:
            raise CommerceError("Choose a delivery or collection option for each seller.")
        if option.requires_address:
            needs_address = True
            if address is None:
                raise CommerceError("Add a delivery address to continue.")
            if not option.serves(address.region):
                raise CommerceError(f"“{option.name}” does not deliver to {address.region}.")
    if needs_address and address.user_id != user.pk:
        raise CommerceError("Choose one of your saved addresses.")

    checkout = Checkout.objects.create(
        buyer=user, total=Decimal("0"), currency=settings.DEFAULT_CURRENCY,
        expires_at=timezone.now() + timedelta(minutes=settings.CHECKOUT_EXPIRY_MINUTES),
    )
    grand_total = Decimal("0")
    for seller_id, lines in by_seller.items():
        option = delivery_by_seller[seller_id]
        subtotal = sum((product.price * quantity for product, quantity in lines), Decimal("0"))
        order = Order.objects.create(
            checkout=checkout, buyer=user, seller_id=seller_id, currency=checkout.currency,
            subtotal=subtotal, delivery_fee=option.fee, total=subtotal + option.fee,
            delivery_method=option.name, delivery_kind=option.kind,
            recipient_name=address.full_name if option.requires_address else (user.get_full_name() or user.username),
            recipient_phone=address.phone_number if option.requires_address else user.phone_number,
            delivery_address=address.as_text() if option.requires_address else "",
            buyer_note=note[:500],
        )
        for product, quantity in lines:
            OrderItem.objects.create(
                order=order, product=product, title=product.title, unit_price=product.price,
                quantity=quantity, line_total=product.price * quantity,
            )
            Product.objects.filter(pk=product.pk).update(stock_quantity=F("stock_quantity") - quantity)
        OrderEvent.objects.create(order=order, to_status=order.status, actor=user, note="Order placed")
        grand_total += order.total
    checkout.total = grand_total
    checkout.save(update_fields=("total",))
    CartItem.objects.filter(user=user).delete()
    return checkout


def _release_stock(checkout):
    for item in OrderItem.objects.filter(order__checkout=checkout, product__isnull=False):
        Product.objects.filter(pk=item.product_id).update(stock_quantity=F("stock_quantity") + item.quantity)


@transaction.atomic
def close_unpaid_checkout(checkout, status=Checkout.Status.CANCELLED, actor=None, note=""):
    """Cancel or expire a checkout that was never paid, returning reserved stock."""
    checkout = Checkout.objects.select_for_update().get(pk=checkout.pk)
    if checkout.status != Checkout.Status.PENDING:
        return checkout
    checkout.status = status
    checkout.save(update_fields=("status",))
    _release_stock(checkout)
    for order in checkout.orders.select_for_update():
        _set_status(order, Order.Status.CANCELLED, actor, note or f"Checkout {checkout.get_status_display().lower()}")
    Payment.objects.filter(checkout=checkout, status=Payment.Status.INITIATED).update(status=Payment.Status.ABANDONED)
    return checkout


def expire_stale_checkouts(now=None):
    """Expire unpaid checkouts, first asking the provider about any payment still in progress."""
    from .payments import get_provider

    now = now or timezone.now()
    expired = 0
    for checkout in Checkout.objects.filter(status=Checkout.Status.PENDING, expires_at__lte=now):
        in_progress = list(checkout.payments.filter(status=Payment.Status.INITIATED))
        for payment in in_progress:
            try:
                verify_and_apply(payment, get_provider(payment.provider))
            except Exception:  # Provider unavailable: fall back to the grace period below.
                logger.warning("Could not check payment %s before expiry", payment.reference, exc_info=True)
        checkout.refresh_from_db()
        if checkout.status != Checkout.Status.PENDING:
            continue  # It was paid (or closed) after all.
        still_open = checkout.payments.filter(status=Payment.Status.INITIATED).exists()
        if still_open and now < checkout.expires_at + timedelta(minutes=PAYMENT_GRACE_MINUTES):
            continue
        close_unpaid_checkout(checkout, status=Checkout.Status.EXPIRED, note="Payment window expired")
        expired += 1
    return expired


# ---------------------------------------------------------------- payments

def start_payment(checkout, provider, callback_url):
    """Create a payment attempt and return the provider URL to send the buyer to."""
    with transaction.atomic():
        checkout = Checkout.objects.select_for_update().select_related("buyer").get(pk=checkout.pk)
        if not checkout.is_payable:
            raise CommerceError("This checkout can no longer be paid.")
        attempt = checkout.payments.count() + 1
        payment = Payment.objects.create(
            checkout=checkout, provider=provider.name, reference=f"{checkout.reference}-P{attempt}",
            amount=checkout.total, currency=checkout.currency,
        )
    try:
        return provider.initialize(payment, checkout.buyer.email, callback_url)
    except PaymentError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)[:300]
        payment.save(update_fields=("status", "failure_reason"))
        raise CommerceError(str(exc)) from exc


def verify_and_apply(payment, provider, raise_errors=False):
    """Ask the provider for the authoritative status and apply it. Safe to call repeatedly.

    With ``raise_errors`` a provider outage raises ``PaymentError`` (webhooks use this so the
    provider retries the event instead of it being marked processed).
    """
    try:
        result = provider.verify(payment)
    except PaymentError as exc:
        logger.warning("Verification of %s failed: %s", payment.reference, exc)
        if raise_errors:
            raise
        return Payment.objects.get(pk=payment.pk)
    return apply_verification(payment, result)


@transaction.atomic
def apply_verification(payment, result):
    checkout_id = Payment.objects.values_list("checkout_id", flat=True).get(pk=payment.pk)
    checkout = Checkout.objects.select_for_update().get(pk=checkout_id)
    payment = Payment.objects.select_for_update().select_related("checkout").get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCEEDED:
        return payment  # Already confirmed: duplicate webhook or callback.
    payment.provider_response = {**(payment.provider_response or {}), "verification": result.raw}
    if result.status == "pending":
        payment.save(update_fields=("provider_response",))
        return payment
    if result.status != "success":
        payment.status = Payment.Status.FAILED
        payment.failure_reason = (result.message or "Payment was not completed.")[:300]
        payment.save(update_fields=("status", "failure_reason", "provider_response"))
        return payment
    if result.amount != payment.amount or result.currency.upper() != payment.currency.upper():
        payment.status = Payment.Status.FAILED
        payment.failure_reason = (
            f"Amount mismatch: expected {payment.currency} {payment.amount}, provider reported "
            f"{result.currency} {result.amount}. Needs staff review."
        )
        payment.save(update_fields=("status", "failure_reason", "provider_response"))
        logger.error("Payment %s amount/currency mismatch", payment.reference)
        return payment

    payment.status = Payment.Status.SUCCEEDED
    payment.verified_at = timezone.now()
    payment.channel = result.channel[:30]
    payment.provider_transaction_id = result.transaction_id[:100]
    if checkout.status != Checkout.Status.PENDING:
        # Money arrived after the checkout closed (expired, cancelled, or already paid by another
        # attempt). Never silently keep it: flag it for a refund and tell the buyer.
        state = "already paid" if checkout.status == Checkout.Status.PAID else checkout.get_status_display().lower()
        payment.failure_reason = f"Paid after checkout was {state}; refund required."
        payment.save()
        logger.error("Payment %s succeeded for closed checkout %s", payment.reference, checkout.reference)
        notify(checkout.buyer, "We received an extra payment",
               f"{cedis(payment.amount)} arrived after {checkout.reference} was {state}. "
               "It will be refunded to you; you do not need to do anything.", reverse("commerce:order_list"))
        return payment
    payment.save()
    checkout.status = Checkout.Status.PAID
    checkout.paid_at = payment.verified_at
    checkout.save(update_fields=("status", "paid_at"))
    for order in checkout.orders.select_for_update().select_related("seller", "buyer"):
        order.paid_at = payment.verified_at
        order.save(update_fields=("paid_at",))
        _set_status(order, Order.Status.PAID, None, f"Payment {payment.reference} verified")
        notify(order.seller, f"New paid order {order.number}", "Prepare the items and update the order status.",
               reverse("commerce:seller_order_detail", args=[order.number]))
    notify(checkout.buyer, "Payment received", f"We received {cedis(checkout.total)} for {checkout.reference}.",
           reverse("commerce:order_list"))
    return payment


# ---------------------------------------------------------------- order status

SELLER_TRANSITIONS = {
    Order.Status.PAID: {Order.Status.PROCESSING, Order.Status.READY_FOR_PICKUP, Order.Status.CANCELLED},
    Order.Status.PROCESSING: {Order.Status.SHIPPED, Order.Status.READY_FOR_PICKUP, Order.Status.CANCELLED},
    Order.Status.SHIPPED: {Order.Status.DELIVERED},
    Order.Status.READY_FOR_PICKUP: {Order.Status.DELIVERED},
}
BUYER_TRANSITIONS = {
    Order.Status.SHIPPED: {Order.Status.COMPLETED},
    Order.Status.READY_FOR_PICKUP: {Order.Status.COMPLETED},
    Order.Status.DELIVERED: {Order.Status.COMPLETED},
}


def allowed_transitions(order, user):
    if user.pk == order.seller_id:
        return SELLER_TRANSITIONS.get(order.status, set())
    if user.pk == order.buyer_id:
        return BUYER_TRANSITIONS.get(order.status, set())
    return set()


def _set_status(order, to_status, actor, note=""):
    from_status = order.status
    order.status = to_status
    order.save(update_fields=("status", "updated_at"))
    OrderEvent.objects.create(order=order, from_status=from_status, to_status=to_status, actor=actor, note=note[:500])


@transaction.atomic
def change_order_status(order, to_status, actor, note="", tracking_reference=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if to_status not in allowed_transitions(order, actor):
        raise CommerceError("That status change is not allowed for this order.")
    if to_status == Order.Status.CANCELLED:
        if not note.strip():
            raise CommerceError("Give the buyer a reason for cancelling.")
        order.cancellation_reason = note[:500]
        order.save(update_fields=("cancellation_reason",))
    if tracking_reference:
        order.tracking_reference = tracking_reference[:100]
        order.save(update_fields=("tracking_reference",))
    _set_status(order, to_status, actor, note)
    other = order.buyer if actor.pk == order.seller_id else order.seller
    url = (reverse("commerce:order_detail", args=[order.number]) if other.pk == order.buyer_id
           else reverse("commerce:seller_order_detail", args=[order.number]))
    notify(other, f"Order {order.number}: {order.get_status_display()}", note[:300], url)
    if to_status == Order.Status.CANCELLED and order.is_paid:
        # A paid order cancelled by the seller is refunded in full and its stock returned.
        _restock(order)
        remaining = order.total - refunded_amount(order)
        if remaining > 0:
            refund_order(order, remaining, actor, f"Seller cancelled: {note}"[:300])
    return order


def _restock(order):
    for item in order.items.filter(product__isnull=False):
        Product.objects.filter(pk=item.product_id).update(stock_quantity=F("stock_quantity") + item.quantity)


def refunded_amount(order):
    return order.refunds.exclude(status=Refund.Status.FAILED).aggregate(total=Sum("amount"))["total"] or Decimal("0")


@transaction.atomic
def refund_order(order, amount, actor, reason, provider=None):
    """Refund part or all of a paid order through the provider that took the payment."""
    from .payments import get_provider

    order = Order.objects.select_for_update().get(pk=order.pk)
    amount = Decimal(amount)
    if not order.is_paid:
        raise CommerceError("Only paid orders can be refunded.")
    if amount <= 0 or amount > order.total - refunded_amount(order):
        raise CommerceError("Refund amount exceeds what remains refundable for this order.")
    payment = order.checkout.payments.filter(status=Payment.Status.SUCCEEDED, failure_reason="").order_by(
        "verified_at").first()
    refund = Refund(order=order, payment=payment, amount=amount, reason=reason[:300], created_by=actor)
    if payment is None:
        refund.status = Refund.Status.FAILED
        refund.save()
        raise CommerceError("No verified payment found for this order.")
    try:
        provider = provider or get_provider(payment.provider)
        status, provider_reference = provider.refund(payment, amount)
        refund.status = Refund.Status.COMPLETED if status == "completed" else Refund.Status.REQUESTED
        refund.provider_reference = provider_reference[:100]
    except PaymentError as exc:
        refund.status = Refund.Status.FAILED
        refund.reason = f"{reason} — provider error: {exc}"[:300]
        logger.error("Refund for %s failed: %s", order.number, exc)
    refund.save()
    if refund.status != Refund.Status.FAILED and refunded_amount(order) >= order.total:
        if order.status != Order.Status.CANCELLED:
            _set_status(order, Order.Status.REFUNDED, actor, reason)
        else:
            OrderEvent.objects.create(order=order, from_status=order.status, to_status=order.status, actor=actor,
                                      note=f"Refund of {cedis(amount)} {refund.get_status_display().lower()}")
    notify(order.buyer, f"Refund for order {order.number}",
           f"{cedis(amount)}: {refund.get_status_display()}.", reverse("commerce:order_detail", args=[order.number]))
    return refund


def needs_payment_refund(payment):
    """A verified payment that did not pay for any order (late or duplicate) and is not refunded yet."""
    return (
        payment.status == Payment.Status.SUCCEEDED and "refund required" in payment.failure_reason
        and not payment.refunds.exclude(status=Refund.Status.FAILED).exists()
    )


@transaction.atomic
def refund_payment(payment, actor, reason="Payment received after checkout closed", provider=None):
    """Refund a whole orphaned payment (one that arrived late or twice) through its provider."""
    from .payments import get_provider

    payment = Payment.objects.select_for_update().select_related("checkout__buyer").get(pk=payment.pk)
    if not needs_payment_refund(payment):
        raise CommerceError("This payment is not waiting for a refund.")
    refund = Refund(order=None, payment=payment, amount=payment.amount, reason=reason[:300], created_by=actor)
    try:
        status, provider_reference = (provider or get_provider(payment.provider)).refund(payment, payment.amount)
        refund.status = Refund.Status.COMPLETED if status == "completed" else Refund.Status.REQUESTED
        refund.provider_reference = provider_reference[:100]
    except PaymentError as exc:
        refund.status = Refund.Status.FAILED
        refund.reason = f"{reason} — provider error: {exc}"[:300]
        logger.error("Refund of payment %s failed: %s", payment.reference, exc)
    refund.save()
    notify(payment.checkout.buyer, "Refund of your extra payment",
           f"{cedis(payment.amount)}: {refund.get_status_display()}.", reverse("commerce:order_list"))
    return refund


def recheck_refund(refund, provider=None):
    """Ask the provider for the latest status of a refund that is still in progress."""
    from .payments import get_provider

    if refund.status != Refund.Status.REQUESTED or refund.payment is None or not refund.provider_reference:
        return refund
    try:
        status = (provider or get_provider(refund.payment.provider)).refund_status(refund.provider_reference)
    except PaymentError as exc:
        logger.warning("Could not re-check refund %s: %s", refund.provider_reference, exc)
        return refund
    mapped = {"completed": Refund.Status.COMPLETED, "failed": Refund.Status.FAILED}.get(status)
    if mapped:
        refund.status = mapped
        refund.save(update_fields=("status",))
        if refund.order_id:
            notify(refund.order.buyer, f"Refund for order {refund.order.number}",
                   f"{cedis(refund.amount)}: {refund.get_status_display()}.",
                   reverse("commerce:order_detail", args=[refund.order.number]))
    return refund
