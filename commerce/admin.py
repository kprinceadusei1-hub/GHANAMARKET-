from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import (
    Address, Checkout, DeliveryOption, Order, OrderEvent, OrderIssue, OrderItem, Payment, PaymentEvent, Refund,
)
from .payments import get_provider


class ReadOnlyAdminMixin:
    """Financial records are created by the system only; staff can inspect but not edit them."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeliveryOption)
class DeliveryOptionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "fee", "regions", "estimated_days", "requires_address", "is_active", "position")
    list_editable = ("fee", "is_active", "position")
    list_filter = ("kind", "is_active")


@admin.register(Address)
class AddressAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("full_name", "user", "city", "region", "created_at")
    search_fields = ("full_name", "user__username", "user__email", "city")


class OrderItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("title", "product", "unit_price", "quantity", "line_total")
    readonly_fields = fields


class OrderEventInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = OrderEvent
    extra = 0
    fields = ("created_at", "from_status", "to_status", "actor", "note")
    readonly_fields = fields


class RefundInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = Refund
    extra = 0
    fields = ("created_at", "amount", "status", "provider_reference", "reason", "created_by")
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "buyer", "seller", "status", "total", "delivery_method", "paid_at", "created_at")
    list_filter = ("status", "delivery_kind", ("paid_at", admin.EmptyFieldListFilter), "created_at")
    search_fields = ("number", "checkout__reference", "buyer__username", "buyer__email", "seller__username")
    date_hierarchy = "created_at"
    list_select_related = ("buyer", "seller")
    inlines = (OrderItemInline, RefundInline, OrderEventInline)
    actions = ("refund_in_full",)
    readonly_fields = (
        "number", "checkout", "buyer", "seller", "status", "currency", "subtotal", "delivery_fee", "total",
        "delivery_method", "delivery_kind", "recipient_name", "recipient_phone", "delivery_address", "buyer_note",
        "tracking_reference", "cancellation_reason", "paid_at", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Refund selected paid orders in full through the payment provider",
                  permissions=("refund",))
    def refund_in_full(self, request, queryset):
        for order in queryset:
            remaining = order.total - services.refunded_amount(order)
            if not order.is_paid or remaining <= 0:
                self.message_user(request, f"{order.number}: nothing refundable.", messages.WARNING)
                continue
            try:
                refund = services.refund_order(order, remaining, request.user, "Refunded by staff")
            except services.CommerceError as exc:
                self.message_user(request, f"{order.number}: {exc}", messages.ERROR)
                continue
            self.log_change(request, order, f"Refund of {order.currency} {remaining}: {refund.get_status_display()}")
            level = messages.ERROR if refund.status == Refund.Status.FAILED else messages.SUCCESS
            self.message_user(request, f"{order.number}: refund {refund.get_status_display().lower()}.", level)

    def has_refund_permission(self, request):
        return request.user.has_perm("commerce.add_refund")


class PaymentInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("reference", "provider", "amount", "status", "channel", "verified_at", "failure_reason")
    readonly_fields = fields


@admin.register(Checkout)
class CheckoutAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("reference", "buyer", "status", "total", "created_at", "paid_at", "expires_at")
    list_filter = ("status", "created_at")
    search_fields = ("reference", "buyer__username", "buyer__email")
    inlines = (PaymentInline,)


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("reference", "provider", "amount", "currency", "status", "channel", "verified_at", "needs_attention")
    list_filter = ("status", "provider", "channel", "created_at")
    search_fields = ("reference", "checkout__reference", "provider_transaction_id", "checkout__buyer__email")
    actions = ("reverify",)

    @admin.display(boolean=True, description="Needs attention")
    def needs_attention(self, payment):
        # Succeeded but flagged (e.g. paid after expiry), or an amount mismatch awaiting review.
        flagged_success = payment.status == Payment.Status.SUCCEEDED and bool(payment.failure_reason)
        return flagged_success or "mismatch" in payment.failure_reason.lower()

    @admin.action(description="Re-verify selected payments with the provider (reconcile)", permissions=("view",))
    def reverify(self, request, queryset):
        for payment in queryset:
            try:
                provider = get_provider(payment.provider)
            except Exception as exc:
                self.message_user(request, f"{payment.reference}: provider unavailable ({exc}).", messages.ERROR)
                continue
            before = payment.status
            payment = services.verify_and_apply(payment, provider)
            self.log_change(request, payment, f"Reconciled with provider: {before} → {payment.status}")
            self.message_user(request, f"{payment.reference}: {before} → {payment.status}.")


@admin.register(PaymentEvent)
class PaymentEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("received_at", "provider", "event_type", "reference", "processed_at", "outcome")
    list_filter = ("provider", "event_type")
    search_fields = ("reference",)


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("order", "amount", "status", "provider_reference", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("order__number", "provider_reference")


@admin.register(OrderIssue)
class OrderIssueAdmin(admin.ModelAdmin):
    list_display = ("order", "kind", "reason", "raised_by", "status", "created_at")
    list_filter = ("status", "kind")
    search_fields = ("order__number", "reason", "raised_by__username")
    fields = ("order", "raised_by", "kind", "reason", "details", "status", "resolution_note", "resolved_by", "resolved_at")
    readonly_fields = ("order", "raised_by", "kind", "reason", "details", "resolved_by", "resolved_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data and obj.status != OrderIssue.Status.OPEN:
            obj.resolved_by = request.user
            obj.resolved_at = timezone.now()
            from marketplace.notifications import notify
            from django.urls import reverse

            view = "commerce:seller_order_detail" if obj.raised_by_id == obj.order.seller_id else "commerce:order_detail"
            notify(obj.raised_by, f"Update on your request for order {obj.order.number}",
                   f"{obj.get_status_display()}. {obj.resolution_note}".strip(),
                   reverse(view, args=[obj.order.number]))
        super().save_model(request, obj, form, change)
