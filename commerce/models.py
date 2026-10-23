"""Cart, checkout, orders, payments and delivery.

Money flow: a buyer's cart becomes one ``Checkout`` (one payment) that is split into one ``Order``
per seller. Orders only become paid when ``services.confirm_payment`` records a payment that was
verified server-side with the provider; browser redirects never mark anything as paid.
"""
import secrets

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from marketplace.models import GhanaRegion, Product


def new_reference(prefix):
    return f"{prefix}-{timezone.now():%y%m%d}-{secrets.token_hex(5).upper()}"


class DeliveryOption(models.Model):
    """Admin-configured delivery or collection method with a transparent flat fee."""

    class Kind(models.TextChoices):
        PICKUP = "pickup", "Collect from seller"
        SELLER = "seller", "Seller delivers"
        COURIER = "courier", "Courier delivery"

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PICKUP)
    description = models.CharField(max_length=200, blank=True)
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    regions = models.CharField(
        max_length=400, blank=True,
        help_text="Comma-separated Ghana regions this option serves. Leave blank for all regions.",
    )
    estimated_days = models.CharField(max_length=40, blank=True, help_text="Shown to buyers, e.g. '1–3 days'.")
    requires_address = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "fee", "name")

    def __str__(self):
        return self.name

    def serves(self, region):
        allowed = [r.strip() for r in self.regions.split(",") if r.strip()]
        return not allowed or region in allowed


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=30)
    region = models.CharField(max_length=30, choices=GhanaRegion.choices)
    city = models.CharField(max_length=100)
    street = models.CharField("Street, area or landmark", max_length=200)
    digital_address = models.CharField(
        "GhanaPost digital address", max_length=20, blank=True, help_text="Optional, e.g. GA-123-4567.",
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-is_default", "-created_at")
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.full_name}, {self.city}"

    def as_text(self):
        parts = [self.street, self.city, self.region]
        if self.digital_address:
            parts.append(self.digital_address)
        return ", ".join(parts)


class CartItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("added_at",)
        constraints = [models.UniqueConstraint(fields=("user", "product"), name="unique_cart_product")]

    def __str__(self):
        return f"{self.quantity} × {self.product}"

    @property
    def line_total(self):
        return self.product.price * self.quantity


class Checkout(models.Model):
    """One buyer payment covering one or more seller orders."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting payment"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    reference = models.CharField(max_length=40, unique=True, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkouts")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = new_reference("CO")
        super().save(*args, **kwargs)

    @property
    def is_payable(self):
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Awaiting payment"
        PAID = "paid", "Paid – awaiting seller"
        PROCESSING = "processing", "Being prepared"
        SHIPPED = "shipped", "On the way"
        READY_FOR_PICKUP = "ready_for_pickup", "Ready for collection"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    number = models.CharField(max_length=40, unique=True, editable=False)
    checkout = models.ForeignKey(Checkout, on_delete=models.PROTECT, related_name="orders")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="seller_orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    # Snapshots: what the buyer agreed to, unaffected by later edits.
    delivery_method = models.CharField(max_length=80)
    delivery_kind = models.CharField(max_length=10, choices=DeliveryOption.Kind.choices)
    recipient_name = models.CharField(max_length=120, blank=True)
    recipient_phone = models.CharField(max_length=30, blank=True)
    delivery_address = models.CharField(max_length=400, blank=True)
    buyer_note = models.CharField(max_length=500, blank=True)
    tracking_reference = models.CharField(max_length=100, blank=True)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("seller", "status"), name="order_seller_status_idx")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = new_reference("GM")
        super().save(*args, **kwargs)

    @property
    def is_paid(self):
        return self.paid_at is not None


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name="order_items")
    title = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} × {self.title}"


class OrderEvent(models.Model):
    """Audit trail of order status changes and important actions."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.order}: {self.from_status} → {self.to_status}"


class Payment(models.Model):
    """One payment attempt for a checkout. Only server-verified attempts may succeed."""

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        SUCCEEDED = "succeeded", "Succeeded (verified)"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    checkout = models.ForeignKey(Checkout, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20)
    reference = models.CharField(max_length=60, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INITIATED, db_index=True)
    channel = models.CharField(max_length=30, blank=True, help_text="Reported by the provider, e.g. mobile_money, card.")
    provider_transaction_id = models.CharField(max_length=100, blank=True)
    failure_reason = models.CharField(max_length=300, blank=True)
    provider_response = models.JSONField(default=dict, blank=True, help_text="Sanitised provider response; never card data.")
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.reference


class PaymentEvent(models.Model):
    """Webhook deliveries, stored once each so duplicates and replays are ignored."""

    provider = models.CharField(max_length=20)
    event_key = models.CharField(max_length=128, help_text="Hash of the signed payload; unique per provider.")
    event_type = models.CharField(max_length=60)
    reference = models.CharField(max_length=60, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("-received_at",)
        constraints = [models.UniqueConstraint(fields=("provider", "event_key"), name="unique_payment_event")]

    def __str__(self):
        return f"{self.provider} {self.event_type} {self.reference}"


class Refund(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested from provider"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        MANUAL = "manual", "Recorded as refunded outside the platform"

    order = models.ForeignKey(
        Order, on_delete=models.PROTECT, related_name="refunds", null=True, blank=True,
        help_text="Empty for a refund of a whole payment that did not pay for any order (late or duplicate).",
    )
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds", null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=300)
    provider_reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Refund {self.amount} for {self.order or self.payment}"


class OrderIssue(models.Model):
    """Buyer- or seller-raised cancellation, return, refund or dispute, resolved by staff or the seller."""

    class Kind(models.TextChoices):
        CANCELLATION = "cancellation", "Cancellation request"
        RETURN = "return", "Return request"
        REFUND = "refund", "Refund request"
        DISPUTE = "dispute", "Dispute"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        RESOLVED = "resolved", "Resolved"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="issues")
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="order_issues")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    reason = models.CharField(max_length=120)
    details = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolution_note = models.CharField(max_length=500, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_kind_display()} for {self.order}"
