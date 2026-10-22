import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from marketplace.forms import SellerReviewForm
from marketplace.models import Product, SellerReview, User
from marketplace.trust import can_review

from . import services
from .forms import AddressForm, CheckoutForm, OrderIssueForm, OrderStatusForm
from .models import Address, CartItem, Checkout, DeliveryOption, Order, OrderIssue, Payment, PaymentEvent
from .payments import WebhookSignatureError, get_provider
from .payments.test_provider import OUTCOME_KEY

logger = logging.getLogger(__name__)


def _safe_provider():
    try:
        return get_provider()
    except Exception:  # Misconfiguration is reported by settings checks; checkout simply stays disabled.
        logger.exception("Payment provider unavailable")
        return None


# ---------------------------------------------------------------- cart

@login_required
def cart(request):
    groups = services.cart_groups(request.user)
    total = sum(group["subtotal"] for group in groups)
    return render(request, "commerce/cart.html", {
        "groups": groups,
        "subtotal": total,
        "has_problems": any(group["problems"] for group in groups),
        "payments_enabled": _safe_provider() is not None,
    })


@login_required
@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product.objects.select_related("category"), pk=product_id)
    try:
        quantity = max(1, int(request.POST.get("quantity", 1)))
        services.add_to_cart(request.user, product, quantity)
    except ValueError:
        messages.error(request, "Enter a valid quantity.")
    except services.CommerceError as exc:
        messages.error(request, str(exc))
        return redirect("product_detail", pk=product.pk)
    else:
        messages.success(request, f"“{product.title}” was added to your cart.")
    if request.POST.get("next") == "checkout":
        return redirect("commerce:checkout")
    return redirect("commerce:cart")


@login_required
@require_POST
def cart_update(request, item_id):
    item = get_object_or_404(CartItem.objects.select_related("product"), pk=item_id, user=request.user)
    try:
        services.set_cart_quantity(item, int(request.POST.get("quantity", item.quantity)))
    except ValueError:
        messages.error(request, "Enter a valid quantity.")
    except services.CommerceError as exc:
        messages.error(request, str(exc))
    return redirect("commerce:cart")


@login_required
@require_POST
def cart_remove(request, item_id):
    CartItem.objects.filter(pk=item_id, user=request.user).delete()
    return redirect("commerce:cart")


# ---------------------------------------------------------------- checkout

@login_required
def checkout(request):
    provider = _safe_provider()
    if provider is None:
        messages.info(request, "Online payment is not available yet. You can still message sellers directly.")
        return redirect("commerce:cart")
    groups = [group for group in services.cart_groups(request.user)]
    if not groups:
        return redirect("commerce:cart")
    if any(group["problems"] for group in groups):
        messages.error(request, "Some items in your cart need attention before checkout.")
        return redirect("commerce:cart")
    form = CheckoutForm(request.user, groups, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                address = form.resolve_address()
                created = services.create_checkout(
                    request.user, form.delivery_by_seller(), address=address, note=form.cleaned_data["note"],
                )
        except services.CommerceError as exc:
            messages.error(request, str(exc))
        else:
            return redirect("commerce:checkout_pay", reference=created.reference)
    subtotal = sum(group["subtotal"] for group in groups)
    return render(request, "commerce/checkout.html", {
        "form": form, "groups": groups, "subtotal": subtotal, "provider": provider,
        "address_option_ids": [str(pk) for pk in DeliveryOption.objects.filter(
            is_active=True, requires_address=True).values_list("pk", flat=True)],
    })


def _own_checkout(request, reference):
    return get_object_or_404(Checkout, reference=reference, buyer=request.user)


@login_required
def checkout_pay(request, reference):
    checkout_obj = _own_checkout(request, reference)
    if checkout_obj.status == Checkout.Status.PENDING and not checkout_obj.is_payable:
        services.close_unpaid_checkout(checkout_obj, status=Checkout.Status.EXPIRED, note="Payment window expired")
        checkout_obj.refresh_from_db()
    provider = _safe_provider()
    if request.method == "POST":
        if provider is None:
            messages.error(request, "Online payment is not available right now.")
        else:
            callback = request.build_absolute_uri(reverse("commerce:payment_callback"))
            try:
                return redirect(services.start_payment(checkout_obj, provider, callback))
            except services.CommerceError as exc:
                messages.error(request, str(exc))
    return render(request, "commerce/checkout_pay.html", {
        "checkout": checkout_obj,
        "orders": checkout_obj.orders.prefetch_related("items").select_related("seller"),
        "provider": provider,
        "last_payment": checkout_obj.payments.first(),
    })


@login_required
@require_POST
def checkout_cancel(request, reference):
    checkout_obj = _own_checkout(request, reference)
    if checkout_obj.status == Checkout.Status.PENDING:
        services.close_unpaid_checkout(checkout_obj, actor=request.user, note="Cancelled by buyer before payment")
        messages.success(request, "Checkout cancelled. Nothing was charged.")
    return redirect("commerce:order_list")


def payment_callback(request):
    """Buyer returns from the provider. The status shown comes from server-side verification only."""
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    payment = Payment.objects.select_related("checkout").filter(reference=reference).first()
    if payment is None:
        raise Http404("Unknown payment")
    provider = _safe_provider()
    if provider is not None and provider.name == payment.provider:
        payment = services.verify_and_apply(payment, provider)
    if payment.status == Payment.Status.SUCCEEDED:
        messages.success(request, "Payment confirmed. The sellers have been notified.")
    elif payment.status == Payment.Status.FAILED:
        messages.error(request, "The payment was not completed. You can try again.")
    else:
        messages.info(request, "We are still waiting for the payment provider to confirm your payment.")
    return redirect("commerce:checkout_pay", reference=payment.checkout.reference)


@csrf_exempt
@require_POST
def payment_webhook(request, provider_name):
    """Signed provider notifications. Each event is processed once; replays and duplicates are ignored."""
    provider = _safe_provider()
    if provider is None or provider.name != provider_name:
        raise Http404()
    try:
        event = provider.parse_webhook(request)
    except WebhookSignatureError:
        logger.warning("Rejected %s webhook with invalid signature", provider_name)
        return HttpResponseBadRequest("invalid signature")
    try:
        with transaction.atomic():
            record, _ = PaymentEvent.objects.get_or_create(
                provider=provider.name, event_key=event.event_key,
                defaults={"event_type": event.event_type[:60], "reference": event.reference[:60],
                          "payload": event.payload},
            )
    except IntegrityError:  # Two identical deliveries raced; the other one is handling it.
        return HttpResponse("duplicate")
    if record.processed_at is not None:
        return HttpResponse("duplicate")
    # A retry of an event whose earlier processing failed falls through and is processed again.
    payment = Payment.objects.filter(reference=event.reference, provider=provider.name).first()
    if payment is None:
        outcome = "No matching payment"
    elif event.event_type == "charge.success":
        # Re-verify with the provider API rather than trusting the event body alone.
        outcome = f"Payment {services.verify_and_apply(payment, provider).status}"
    else:
        outcome = "Ignored event type"
    record.processed_at = timezone.now()
    record.outcome = outcome[:200]
    record.save(update_fields=("processed_at", "outcome"))
    return HttpResponse("ok")


@login_required
def test_payment(request, reference):
    """Development-only stand-in for a provider's hosted payment page."""
    payment = get_object_or_404(Payment, reference=reference, checkout__buyer=request.user, provider="test")
    provider = _safe_provider()
    if not settings.DEBUG or provider is None or provider.name != "test":
        raise Http404()
    if request.method == "POST" and payment.status == Payment.Status.INITIATED:
        outcome = "success" if request.POST.get("outcome") == "success" else "failed"
        payment.provider_response = {**payment.provider_response, OUTCOME_KEY: outcome}
        payment.save(update_fields=("provider_response",))
        return redirect(f"{reverse('commerce:payment_callback')}?reference={payment.reference}")
    return render(request, "commerce/test_payment.html", {"payment": payment})


# ---------------------------------------------------------------- buyer orders

@login_required
def order_list(request):
    return render(request, "commerce/order_list.html", {
        "checkouts": Checkout.objects.filter(buyer=request.user).prefetch_related("orders__items", "orders__seller"),
    })


@login_required
def order_detail(request, number):
    order = get_object_or_404(
        Order.objects.select_related("seller", "checkout").prefetch_related("items", "events", "issues", "refunds"),
        number=number, buyer=request.user,
    )
    if request.method == "POST":
        if request.POST.get("action") == "complete":
            try:
                services.change_order_status(order, Order.Status.COMPLETED, request.user, "Buyer confirmed receipt")
                messages.success(request, "Thanks for confirming. The order is complete.")
            except services.CommerceError as exc:
                messages.error(request, str(exc))
        return redirect("commerce:order_detail", number=order.number)
    return render(request, "commerce/order_detail.html", {
        "order": order,
        "can_complete": Order.Status.COMPLETED in services.allowed_transitions(order, request.user),
        "issue_form": OrderIssueForm(order) if order.is_paid else None,
        "status_labels": Order.Status.choices,
        "review_form": SellerReviewForm() if can_review(order, request.user) else None,
        "review": SellerReview.objects.filter(order=order).first(),
    })


@login_required
@require_POST
def order_issue(request, number):
    order = get_object_or_404(Order, number=number)
    if request.user.pk not in {order.buyer_id, order.seller_id}:
        raise Http404()
    if not order.is_paid:
        messages.error(request, "Unpaid orders can simply be cancelled.")
        return redirect("commerce:order_detail", number=number)
    if order.issues.filter(status=OrderIssue.Status.OPEN, raised_by=request.user).exists():
        messages.info(request, "You already have an open request for this order. Our team and the seller will respond.")
        return redirect("commerce:order_detail", number=number)
    form = OrderIssueForm(order, request.POST)
    if form.is_valid():
        issue = form.save(commit=False)
        issue.order, issue.raised_by = order, request.user
        issue.save()
        from marketplace.notifications import notify

        notify(order.seller, f"{issue.get_kind_display()} for order {order.number}", issue.reason,
               reverse("commerce:seller_order_detail", args=[order.number]))
        messages.success(request, "Request sent. The seller and our support team can now see it.")
    else:
        messages.error(request, "Please choose a request type and give a short reason.")
    return redirect("commerce:order_detail", number=number)


# ---------------------------------------------------------------- seller orders

def _require_seller(request):
    if request.user.role != User.Role.SELLER:
        raise Http404()


@login_required
def seller_orders(request):
    _require_seller(request)
    orders = Order.objects.filter(seller=request.user).exclude(status=Order.Status.PENDING_PAYMENT)
    status = request.GET.get("status", "")
    if status in dict(Order.Status.choices):
        orders = orders.filter(status=status)
    return render(request, "commerce/seller_orders.html", {
        "orders": orders.select_related("buyer").prefetch_related("items"),
        "selected_status": status,
        "status_options": [(v, l) for v, l in Order.Status.choices if v != Order.Status.PENDING_PAYMENT],
    })


@login_required
def seller_order_detail(request, number):
    _require_seller(request)
    order = get_object_or_404(
        Order.objects.select_related("buyer").prefetch_related("items", "events", "issues", "refunds"),
        number=number, seller=request.user,
    )
    if order.status == Order.Status.PENDING_PAYMENT:
        raise Http404()
    transitions = services.allowed_transitions(order, request.user)
    form = OrderStatusForm(transitions, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.change_order_status(
                order, form.cleaned_data["to_status"], request.user,
                note=form.cleaned_data["note"], tracking_reference=form.cleaned_data["tracking_reference"],
            )
        except services.CommerceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Order updated and the buyer was notified.")
            return redirect("commerce:seller_order_detail", number=order.number)
    return render(request, "commerce/seller_order_detail.html", {
        "order": order, "status_form": form if transitions else None, "status_labels": Order.Status.choices,
    })


# ---------------------------------------------------------------- addresses

@login_required
def addresses(request):
    form = AddressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        address = form.save(commit=False)
        address.user = request.user
        address.is_default = not Address.objects.filter(user=request.user).exists()
        address.save()
        messages.success(request, "Address saved.")
        return redirect("commerce:addresses")
    return render(request, "commerce/addresses.html", {
        "form": form, "addresses": Address.objects.filter(user=request.user),
    })


@login_required
@require_POST
def address_delete(request, pk):
    Address.objects.filter(pk=pk, user=request.user).delete()
    messages.success(request, "Address removed.")
    return redirect("commerce:addresses")
