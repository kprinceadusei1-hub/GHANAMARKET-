from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models


class GhanaRegion(models.TextChoices):
    AHAFO = "Ahafo", "Ahafo"
    ASHANTI = "Ashanti", "Ashanti"
    BONO = "Bono", "Bono"
    BONO_EAST = "Bono East", "Bono East"
    CENTRAL = "Central", "Central"
    EASTERN = "Eastern", "Eastern"
    GREATER_ACCRA = "Greater Accra", "Greater Accra"
    NORTH_EAST = "North East", "North East"
    NORTHERN = "Northern", "Northern"
    OTI = "Oti", "Oti"
    SAVANNAH = "Savannah", "Savannah"
    UPPER_EAST = "Upper East", "Upper East"
    UPPER_WEST = "Upper West", "Upper West"
    VOLTA = "Volta", "Volta"
    WESTERN = "Western", "Western"
    WESTERN_NORTH = "Western North", "Western North"


class User(AbstractUser):
    class Role(models.TextChoices):
        BUYER = "buyer", "Buyer"
        SELLER = "seller", "Seller"

    class SellerStatus(models.TextChoices):
        PENDING = "pending", "Waiting for admin approval"
        APPROVED = "approved", "Approved to sell"
        REJECTED = "rejected", "Not approved"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    phone_number = models.CharField(max_length=30, blank=True)
    show_phone = models.BooleanField(
        default=True, help_text="Signed-in buyers can tap “Show phone number” on your ads to call, text or WhatsApp you.",
    )
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(
        max_length=30, choices=GhanaRegion.choices, blank=True, default=""
    )
    country = models.CharField(max_length=2, default=settings.DEFAULT_COUNTRY)
    seller_status = models.CharField(
        max_length=10, choices=SellerStatus.choices, default=SellerStatus.APPROVED,
        help_text="Sellers can post ads only once approved. New seller requests start as pending.",
    )
    seller_requested_at = models.DateTimeField(null=True, blank=True)
    seller_review_note = models.CharField(
        max_length=300, blank=True, help_text="Shown to the person when their seller request is not approved.",
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="Set only when staff approve a seller verification. Drives the 'Verified seller' badge.",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def can_sell(self):
        return self.role == self.Role.SELLER and self.seller_status == self.SellerStatus.APPROVED

    @property
    def whatsapp_number(self):
        """International digits for wa.me links (e.g. 233241112222), or "" if not a usable Ghana number."""
        digits = "".join(ch for ch in self.phone_number or "" if ch.isdigit())
        if len(digits) == 10 and digits.startswith("0"):
            digits = "233" + digits[1:]
        return digits if len(digits) == 12 and digits.startswith("233") else ""

    @property
    def phone_display(self):
        """Ghana number written the local way, e.g. 024 111 2222."""
        digits = self.whatsapp_number
        return f"0{digits[3:5]} {digits[5:8]} {digits[8:]}" if digits else ""

    @property
    def can_be_called(self):
        return bool(self.show_phone and self.whatsapp_number)

    def request_seller_approval(self):
        from django.utils import timezone

        self.role = self.Role.SELLER
        self.seller_status = self.SellerStatus.PENDING
        self.seller_requested_at = timezone.now()
        self.seller_review_note = ""

    @property
    def is_verified_seller(self):
        return self.role == self.Role.SELLER and self.verified_at is not None

    def has_blocked(self, other):
        return UserBlock.objects.filter(blocker=self, blocked=other).exists()

    @staticmethod
    def blocked_between(first, second):
        return UserBlock.objects.filter(
            models.Q(blocker=first, blocked=second) | models.Q(blocker=second, blocked=first)
        ).exists()


class Category(models.Model):
    """Admin-managed listing category. Top-level categories may have one level of subcategories."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=60, unique=True)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children",
        limit_choices_to={"parent__isnull": True},
    )
    icon = models.SlugField(
        max_length=40, blank=True,
        help_text="Icon key used by the site templates, e.g. vehicles, property. Defaults to the top-level slug.",
    )
    description = models.CharField(max_length=200, blank=True)
    price_label = models.CharField(
        max_length=40, blank=True, help_text="Optional price label, e.g. 'Monthly rent' or 'Salary per month'."
    )
    allows_checkout = models.BooleanField(
        default=True, help_text="Whether sellers may enable online checkout for listings in this category."
    )
    is_restricted = models.BooleanField(
        default=False, help_text="Regulated category: listings get extra admin scrutiny and show the restriction note."
    )
    restriction_note = models.CharField(max_length=300, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("position", "name")
        verbose_name_plural = "categories"

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    @property
    def top_level(self):
        return self.parent if self.parent_id else self

    @property
    def icon_key(self):
        return self.icon or self.top_level.slug

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.parent_id and self.parent.parent_id:
            raise ValidationError({"parent": "Subcategories can only be one level deep."})
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({"parent": "A category cannot be its own parent."})

    def attribute_definitions(self):
        """Attributes for this category, including those inherited from its parent."""
        ids = [self.pk] + ([self.parent_id] if self.parent_id else [])
        return CategoryAttribute.objects.filter(category_id__in=ids).order_by("position", "label")


class CategoryAttribute(models.Model):
    """A category-specific listing field, e.g. a vehicle's year or a property's bedrooms."""

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        NUMBER = "number", "Number"
        CHOICE = "choice", "Choice from a list"
        BOOLEAN = "boolean", "Yes / no"

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="attributes")
    key = models.SlugField(max_length=40, help_text="Storage key, e.g. year. Do not change once listings use it.")
    label = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    choices = models.TextField(blank=True, help_text="For 'choice' attributes: one option per line.")
    unit = models.CharField(max_length=20, blank=True, help_text="Optional unit shown after numbers, e.g. km.")
    help_text = models.CharField(max_length=150, blank=True)
    is_required = models.BooleanField(default=False)
    is_filterable = models.BooleanField(default=True, help_text="Show as a filter when browsing this category.")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "label")
        constraints = [
            models.UniqueConstraint(fields=("category", "key"), name="unique_category_attribute_key"),
        ]

    def __str__(self):
        return f"{self.category}: {self.label}"

    @property
    def choice_list(self):
        return [line.strip() for line in self.choices.splitlines() if line.strip()]


class Product(models.Model):
    class Category(models.TextChoices):
        """Slugs of the original launch categories (seeded as Category rows); kept for code and tests."""
        PHONES_TECH = "phones-tech", "Phones & Tech"
        VEHICLES = "vehicles", "Cars & Vehicles"
        HOME_LIVING = "home-living", "Home & Living"
        FASHION = "fashion", "Fashion"
        PROPERTY = "property", "Property"
        BUSINESS_SERVICES = "business-services", "Business & Services"
        OTHER = "other", "Other"

    class Condition(models.TextChoices):
        NEW = "new", "New"
        LIKE_NEW = "like-new", "Like new"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting admin review"
        PUBLISHED = "published", "Published"
        DRAFT = "draft", "Draft"
        REJECTED = "rejected", "Needs changes"
        SOLD = "sold", "Sold"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="products",
        limit_choices_to={"role": User.Role.SELLER},
    )
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=5000)
    # String reference: inside this class body "Category" is the legacy slug-constants class.
    category = models.ForeignKey(
        "marketplace.Category", on_delete=models.PROTECT, to_field="slug", db_column="category",
        related_name="products", limit_choices_to={"parent__isnull": True},
    )
    subcategory = models.ForeignKey(
        "marketplace.Category", on_delete=models.PROTECT, null=True, blank=True,
        related_name="subcategory_products", limit_choices_to={"parent__isnull": False},
    )
    attributes = models.JSONField(default=dict, blank=True)
    brand = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=80, blank=True)
    included_items = models.CharField(max_length=500, blank=True)
    condition = models.CharField(
        max_length=10, choices=Condition.choices, default=Condition.GOOD
    )
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    price_negotiable = models.BooleanField(default=False)
    allows_checkout = models.BooleanField(
        default=False, help_text="Buyers can add this listing to their cart and pay online.",
    )
    allows_direct_contact = models.BooleanField(
        default=True, help_text="Buyers can message the seller about this listing.",
    )
    stock_quantity = models.PositiveIntegerField(
        default=1, help_text="Units available for online checkout.",
    )
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)
    image = models.ImageField(upload_to="products/", blank=True)
    city = models.CharField(max_length=100)
    region = models.CharField(
        max_length=30, choices=GhanaRegion.choices, blank=True, default=""
    )
    country = models.CharField(max_length=2, default=settings.DEFAULT_COUNTRY)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    moderation_note = models.CharField(max_length=500, blank=True)
    risk_flags = models.CharField(
        max_length=500, blank=True,
        help_text="Automatic moderation hints (flagged words, possible duplicates). Never shown to buyers.",
    )
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "is_demo", "-created_at"), name="product_public_recent_idx"),
            models.Index(fields=("category", "status"), name="product_category_status_idx"),
            models.Index(fields=("region", "status"), name="product_region_status_idx"),
            models.Index(fields=("price",), name="product_price_idx"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.subcategory_id and self.subcategory.parent_id and self.subcategory.parent.slug != self.category_id:
            raise ValidationError({"subcategory": "Choose a subcategory that belongs to the selected category."})

    @property
    def can_checkout(self):
        """Online checkout is offered only when the seller enabled it, the category allows it and stock remains."""
        return (
            self.allows_checkout and self.category.allows_checkout and self.stock_quantity > 0
            and self.status == self.Status.PUBLISHED and not self.is_demo and self.seller.is_active
        )

    @property
    def card_tags(self):
        """Short tags for listing cards (condition plus up to two text details), without extra queries."""
        tags = [self.get_condition_display()]
        for value in (self.attributes or {}).values():
            if isinstance(value, str) and value and len(tags) < 3:
                tags.append(value)
        return tags

    @property
    def category_label(self):
        return self.subcategory.name if self.subcategory_id else self.category.name

    def attribute_items(self):
        """(label, display value) pairs for this listing's category attributes, in definition order."""
        if not self.attributes:
            return []
        category = self.subcategory or self.category
        items = []
        for definition in category.attribute_definitions():
            value = self.attributes.get(definition.key)
            if value in (None, ""):
                continue
            if definition.kind == CategoryAttribute.Kind.BOOLEAN:
                value = "Yes" if value else "No"
            elif definition.kind == CategoryAttribute.Kind.NUMBER:
                # Group digits only for measured quantities (98,000 km); years and counts stay plain.
                grouping = "," if definition.unit else ""
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    value = str(value)
                elif isinstance(value, int):
                    value = f"{value:{grouping}}"
                else:
                    value = f"{value:{grouping}.2f}".rstrip("0").rstrip(".")
                if definition.unit:
                    value = f"{value} {definition.unit}"
            items.append((definition.label, value))
        return items


class ProductPhoto(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to="products/")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "pk")

    def __str__(self):
        return f"Photo for {self.product}"


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="favorites"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "product"), name="unique_user_favorite_product")
        ]

    def __str__(self):
        return f"{self.user} saved {self.product}"


class ListingReport(models.Model):
    class Reason(models.TextChoices):
        SCAM = "scam", "Suspected scam or fraud"
        COUNTERFEIT = "counterfeit", "Counterfeit or misleading item"
        PROHIBITED = "prohibited", "Prohibited or unsafe item"
        WRONG_CATEGORY = "wrong-category", "Wrong or misleading category"
        OTHER = "other", "Other concern"

    class Status(models.TextChoices):
        OPEN = "open", "Needs admin review"
        REVIEWED = "reviewed", "Reviewed"
        DISMISSED = "dismissed", "Dismissed"

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="reports"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listing_reports",
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("product", "reporter"),
                name="unique_listing_report_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.get_reason_display()} report for {self.product}"


class Conversation(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="conversations"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="buyer_conversations",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_conversations",
    )
    # When each participant last opened the thread; messages from the other person after this are unread.
    buyer_last_read_at = models.DateTimeField(null=True, blank=True)
    seller_last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("product", "buyer"),
                name="unique_buyer_conversation_per_product",
            ),
            models.CheckConstraint(
                condition=~models.Q(buyer=models.F("seller")),
                name="conversation_buyer_is_not_seller",
            ),
        ]

    def __str__(self):
        return f"{self.product.title}: {self.buyer} and {self.seller}"

    def mark_read(self, user):
        from django.utils import timezone

        field = "buyer_last_read_at" if user.pk == self.buyer_id else "seller_last_read_at"
        setattr(self, field, timezone.now())
        Conversation.objects.filter(pk=self.pk).update(**{field: getattr(self, field)})

    @staticmethod
    def unread_filter(user):
        """Q matching messages that ``user`` has not read yet, for use on Message querysets."""
        return (
            models.Q(conversation__buyer=user) & ~models.Q(sender=user)
            & (models.Q(conversation__buyer_last_read_at__isnull=True)
               | models.Q(created_at__gt=models.F("conversation__buyer_last_read_at")))
        ) | (
            models.Q(conversation__seller=user) & ~models.Q(sender=user)
            & (models.Q(conversation__seller_last_read_at__isnull=True)
               | models.Q(created_at__gt=models.F("conversation__seller_last_read_at")))
        )


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_marketplace_messages",
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Message from {self.sender} in conversation {self.conversation_id}"


class SearchTerm(models.Model):
    """Anonymous count of searches that returned results; powers "popular searches"."""

    term = models.CharField(max_length=80, unique=True)
    hits = models.PositiveIntegerField(default=0)
    last_searched_at = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False, help_text="Hide from popular searches, e.g. offensive or misleading terms.")

    class Meta:
        ordering = ("-hits",)

    def __str__(self):
        return self.term

    @classmethod
    def record(cls, query):
        from django.db.models import F

        term = " ".join(query.lower().split())[:80]
        if len(term) < 2:
            return
        updated = cls.objects.filter(term=term).update(hits=F("hits") + 1)
        if not updated:
            cls.objects.get_or_create(term=term, defaults={"hits": 1})


class Notification(models.Model):
    """In-app notification; email copies are sent where configured."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("user", "is_read"), name="notification_unread_idx")]

    def __str__(self):
        return self.title


def private_storage():
    """Storage for identity documents: outside MEDIA_ROOT, never served publicly."""
    import os

    from django.core.files.storage import FileSystemStorage

    if getattr(settings, "PRIVATE_S3_BUCKET", "") and not settings.DEBUG:
        from storages.backends.s3 import S3Storage

        # Private bucket: no public URL; the staff-only view streams documents through the app.
        return S3Storage(**settings.S3_CONNECTION, bucket_name=settings.PRIVATE_S3_BUCKET, querystring_auth=True,
                         querystring_expire=300)

    class PrivateStorage(FileSystemStorage):
        # Read the setting on every access so tests and deployments can relocate it.
        @property
        def base_location(self):
            return settings.PRIVATE_MEDIA_ROOT

        @property
        def location(self):
            return os.path.abspath(self.base_location)

        @property
        def base_url(self):
            return None

    return PrivateStorage()


class SellerVerification(models.Model):
    """A seller's request to be verified. Only an approval by staff grants the badge."""

    class Kind(models.TextChoices):
        GHANA_CARD = "ghana_card", "Ghana Card (individual)"
        BUSINESS = "business", "Registered business"

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verifications")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    legal_name = models.CharField(max_length=150, help_text="Name exactly as on the document.")
    document_number = models.CharField(
        max_length=40, help_text="Ghana Card number (GHA-XXXXXXXXX-X) or business registration number.",
    )
    document = models.FileField(upload_to="verifications/%Y/%m/", storage=private_storage)
    business_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer_note = models.CharField(max_length=300, blank=True, help_text="Shown to the seller when rejected.")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_kind_display()} for {self.user}"

    @property
    def masked_document_number(self):
        number = self.document_number
        return number if len(number) <= 4 else "•" * (len(number) - 4) + number[-4:]


class SellerReview(models.Model):
    """A rating a buyer can leave once per completed order."""

    order = models.OneToOneField("commerce.Order", on_delete=models.CASCADE, related_name="review")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_received")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_given")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    comment = models.CharField(max_length=500, blank=True)
    is_hidden = models.BooleanField(default=False, help_text="Hidden by staff, e.g. abusive language.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_1_to_5"),
        ]

    def __str__(self):
        return f"{self.rating}★ for {self.seller}"


class UserBlock(models.Model):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("blocker", "blocked"), name="unique_user_block"),
            models.CheckConstraint(condition=~models.Q(blocker=models.F("blocked")), name="no_self_block"),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


class UserReport(models.Model):
    class Reason(models.TextChoices):
        SCAM = "scam", "Scam or fraud attempt"
        HARASSMENT = "harassment", "Harassment or abusive messages"
        FAKE = "fake", "Fake or impersonating account"
        NO_SHOW = "no_show", "Did not complete an agreed deal"
        OTHER = "other", "Other concern"

    class Status(models.TextChoices):
        OPEN = "open", "Needs admin review"
        ACTIONED = "actioned", "Action taken"
        DISMISSED = "dismissed", "Dismissed"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_reports_made")
    reported = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_reports_received")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_reason_display()}: {self.reported}"


class ProhibitedTerm(models.Model):
    """Words or phrases checked when sellers submit listings."""

    class Action(models.TextChoices):
        BLOCK = "block", "Block the listing"
        FLAG = "flag", "Allow but flag for moderators"

    term = models.CharField(max_length=80, unique=True)
    action = models.CharField(max_length=5, choices=Action.choices, default=Action.FLAG)
    reason = models.CharField(max_length=200, blank=True, help_text="Shown to sellers when a listing is blocked.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("term",)

    def __str__(self):
        return self.term


class SupportRequest(models.Model):
    """Help requests, including suspension appeals from people who cannot sign in."""

    class Topic(models.TextChoices):
        ACCOUNT = "account", "My account"
        APPEAL = "appeal", "Appeal an account suspension or removed listing"
        ORDER = "order", "An order or payment"
        SAFETY = "safety", "Safety or fraud concern"
        SELLING = "selling", "Selling on GhanaMarket"
        PRIVACY = "privacy", "Privacy or data request"
        OTHER = "other", "Something else"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ANSWERED = "answered", "Answered"
        CLOSED = "closed", "Closed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="support_requests")
    email = models.EmailField()
    topic = models.CharField(max_length=10, choices=Topic.choices)
    subject = models.CharField(max_length=120)
    message = models.TextField(max_length=3000)
    reference = models.CharField(max_length=60, blank=True, help_text="Order number or listing link, if any.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    staff_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_topic_display()}: {self.subject}"


class PromotionQuerySet(models.QuerySet):
    def active(self, now=None):
        from django.utils import timezone

        now = now or timezone.now()
        return self.filter(is_active=True, starts_at__lte=now, ends_at__gt=now)


class Promotion(models.Model):
    """A staff-arranged boost for a listing. Shown to buyers with a visible "Promoted" label."""

    class Placement(models.TextChoices):
        HOMEPAGE = "homepage", "Homepage featured products"
        CATEGORY = "category", "Top of its category and search results"
        BOTH = "both", "Homepage and category"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="promotions")
    placement = models.CharField(max_length=10, choices=Placement.choices, default=Placement.BOTH)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="Amount agreed with the seller, for records only. No payment is collected through the site.",
    )
    note = models.CharField(max_length=300, blank=True, help_text="Internal note, e.g. launch partner or campaign.")
    is_active = models.BooleanField(default=True, help_text="Untick to stop the promotion early.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PromotionQuerySet.as_manager()

    class Meta:
        ordering = ("-starts_at",)
        constraints = [
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="promotion_ends_after_start"),
        ]

    def __str__(self):
        return f"{self.product} ({self.get_placement_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.product_id and (self.product.status != Product.Status.PUBLISHED or self.product.is_demo):
            raise ValidationError({"product": "Only live, real listings can be promoted."})
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "The promotion must end after it starts."})

    @property
    def is_running(self):
        from django.utils import timezone

        return self.is_active and self.starts_at <= timezone.now() < self.ends_at
