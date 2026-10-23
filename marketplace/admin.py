from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils.html import format_html

from django.urls import reverse
from django.utils import timezone

from . import moderation
from .notifications import notify
from .models import (
    Promotion,
    ProhibitedTerm, SellerReview, SellerVerification, SupportRequest, UserBlock, UserReport,
    Category, CategoryAttribute, Conversation, Favorite, ListingReport, Message, Product, ProductPhoto, SearchTerm, User,
)


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0
    fields = ("position", "label", "key", "kind", "choices", "unit", "is_required", "is_filterable", "help_text")


class SubcategoryInline(admin.TabularInline):
    model = Category
    fk_name = "parent"
    extra = 0
    fields = ("position", "name", "slug", "is_active", "allows_checkout", "is_restricted")
    prepopulated_fields = {"slug": ("name",)}
    verbose_name = "subcategory"
    verbose_name_plural = "subcategories"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("__str__", "slug", "position", "is_active", "allows_checkout", "is_restricted", "listing_count")
    list_editable = ("position", "is_active")
    list_filter = ("parent", "is_active", "allows_checkout", "is_restricted")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (SubcategoryInline, CategoryAttributeInline)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and (Product.objects.filter(category=obj).exists() or Product.objects.filter(subcategory=obj).exists()):
            readonly.append("slug")  # Listings point at this slug; renaming it would break them.
        return tuple(readonly)

    def get_prepopulated_fields(self, request, obj=None):
        return {} if "slug" in self.get_readonly_fields(request, obj) else super().get_prepopulated_fields(request, obj)

    fieldsets = (
        (None, {"fields": ("name", "slug", "parent", "icon", "description", "position", "is_active")}),
        ("Selling rules", {"fields": ("price_label", "allows_checkout", "is_restricted", "restriction_note")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("parent").annotate(
            _listing_count=Count("products", distinct=True) + Count("subcategory_products", distinct=True)
        )

    @admin.display(description="Listings", ordering="_listing_count")
    def listing_count(self, category):
        return category._listing_count

    def get_inlines(self, request, obj):
        # Subcategories cannot have their own subcategories.
        if obj is not None and obj.parent_id:
            return (CategoryAttributeInline,)
        return self.inlines


@admin.register(SearchTerm)
class SearchTermAdmin(admin.ModelAdmin):
    list_display = ("term", "hits", "last_searched_at", "is_hidden")
    list_editable = ("is_hidden",)
    search_fields = ("term",)
    readonly_fields = ("term", "hits", "last_searched_at")

    def has_add_permission(self, request):
        return False


class RiskFlagFilter(admin.SimpleListFilter):
    title = "risk flags"
    parameter_name = "risk"

    def lookups(self, request, model_admin):
        return (("flagged", "Has risk flags"), ("clean", "No risk flags"))

    def queryset(self, request, queryset):
        if self.value() == "flagged":
            return queryset.exclude(risk_flags="")
        if self.value() == "clean":
            return queryset.filter(risk_flags="")
        return queryset


class SellerActivityFilter(admin.SimpleListFilter):
    title = "seller marketplace activity"
    parameter_name = "marketplace_activity"

    def lookups(self, request, model_admin):
        return (("live", "Has live listings"), ("none", "No live listings"))

    def queryset(self, request, queryset):
        if self.value() == "live":
            return queryset.filter(
                products__status=Product.Status.PUBLISHED,
                products__is_demo=False,
            ).distinct()
        if self.value() == "none":
            return queryset.exclude(
                products__status=Product.Status.PUBLISHED,
                products__is_demo=False,
            ).distinct()
        return queryset


class ProductPhotoInline(admin.TabularInline):
    model = ProductPhoto
    extra = 0
    fields = ("photo_preview", "image", "position")
    readonly_fields = ("photo_preview",)

    @admin.display(description="Photo preview")
    def photo_preview(self, photo):
        if not photo.image:
            return "No image"
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" alt="Listing photo" '
            'style="width:120px;height:90px;object-fit:contain;background:#f1f3f1;'
            'border-radius:6px"></a>',
            photo.image.url,
            photo.image.url,
        )


@admin.register(User)
class MarketplaceUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Marketplace profile", {"fields": ("role", "seller_status", "seller_requested_at", "seller_review_note", "phone_number", "city", "region", "country")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Marketplace profile", {"fields": ("email", "role", "phone_number", "city", "region", "country")}),
    )
    list_display = ("username", "email", "role", "seller_status", "city", "region", "active_listing_count", "is_staff", "is_active")
    list_filter = ("role", "seller_status", "region", "is_staff", "is_active", SellerActivityFilter)
    search_fields = ("username", "email", "phone_number", "city")
    actions = ("suspend_member_accounts", "reactivate_member_accounts")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            live_listing_count=Count(
                "products",
                filter=Q(
                    products__status=Product.Status.PUBLISHED,
                    products__is_demo=False,
                ),
                distinct=True,
            )
        )

    @admin.display(description="Live listings", ordering="live_listing_count")
    def active_listing_count(self, user):
        return user.live_listing_count

    PRIVILEGED_FIELDS = ("is_staff", "is_superuser", "groups", "user_permissions")

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and (obj.is_staff or obj.is_superuser or obj.pk == request.user.pk):
            readonly.append("is_active")
        if not request.user.is_superuser:
            # Only superusers grant staff status, superuser status, groups or permissions (incl. their own).
            readonly.extend(field for field in self.PRIVILEGED_FIELDS if field not in readonly)
        return tuple(readonly)

    def has_change_permission(self, request, obj=None):
        # Non-superusers may not edit (or reset the password of) other staff or any superuser.
        if obj is not None and not request.user.is_superuser and (
            obj.is_superuser or (obj.is_staff and obj.pk != request.user.pk)
        ):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # User deletion cascades to their listings and messages; account access is
        # managed with the reversible suspension/reactivation actions instead.
        return False

    @admin.action(description="Suspend selected member accounts (staff protected)", permissions=("change",))
    def suspend_member_accounts(self, request, queryset):
        targets = queryset.filter(is_active=True, is_staff=False, is_superuser=False)
        changed = 0
        for member in targets.iterator():
            member.is_active = False
            member.save(update_fields=("is_active",))
            hidden = Product.objects.filter(seller=member, status=Product.Status.PUBLISHED).update(
                status=Product.Status.DRAFT, moderation_note="Hidden because the account was suspended.")
            self.log_change(request, member, f"Member account suspended by an administrator; {hidden} live ad(s) hidden.")
            changed += 1
        self.message_user(request, f"{changed} member account(s) suspended.", messages.WARNING)

    @admin.action(description="Reactivate selected member accounts (staff protected)", permissions=("change",))
    def reactivate_member_accounts(self, request, queryset):
        targets = queryset.filter(is_active=False, is_staff=False, is_superuser=False)
        changed = 0
        for member in targets.iterator():
            member.is_active = True
            member.save(update_fields=("is_active",))
            self.log_change(request, member, "Member account reactivated by an administrator.")
            changed += 1
        self.message_user(request, f"{changed} member account(s) reactivated.", messages.SUCCESS)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        # Deleting would cascade to conversations, reports and promotions (scam evidence, fee records).
        # Remove listings from public view by changing their status instead.
        return False

    change_list_template = "admin/marketplace/product/change_list.html"
    change_form_template = "admin/marketplace/product/change_form.html"
    list_display = ("title", "seller", "price", "currency", "category", "region", "status_label", "photo_count", "report_count", "has_risk_flags", "created_at")
    list_filter = ("status", RiskFlagFilter, "category", "condition", "region", "country", "is_demo")
    list_select_related = ("seller", "category")
    search_fields = ("title", "brand", "model", "description", "seller__username", "seller__email", "city")
    readonly_fields = ("status_label", "risk_flags", "seller_details", "main_photo_preview", "created_at", "updated_at")
    actions = None
    list_per_page = 25
    inlines = (ProductPhotoInline,)
    fieldsets = (
        ("Review decision", {
            "fields": ("status_label", "risk_flags", "moderation_note"),
            "description": "Inspect the item details, every photo, and seller information before publishing. Request changes with a clear note when needed.",
        }),
        ("Item details", {
            "fields": (
                "title", "category", "subcategory", "brand", "model", "condition",
                "price", "currency", "price_negotiable", "included_items",
                "description", "attributes",
            ),
        }),
        ("Photos and location", {
            "fields": ("main_photo_preview", "image", "city", "region", "country"),
        }),
        ("Seller and record", {
            "fields": ("seller_details", "is_demo", "created_at", "updated_at"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("seller", "category").annotate(
            open_report_count=Count(
                "reports",
                filter=Q(reports__status=ListingReport.Status.OPEN),
                distinct=True,
            ),
            additional_photo_count=Count("photos", distinct=True),
        )

    def get_ordering(self, request):
        return (
            Case(
                When(status=Product.Status.PENDING, then=Value(0)),
                When(status=Product.Status.REJECTED, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            "-created_at",
        )

    @admin.display(description="Open reports", ordering="open_report_count")
    @admin.display(boolean=True, description="Risk flags")
    def has_risk_flags(self, product):
        return bool(product.risk_flags)

    def report_count(self, product):
        return product.open_report_count

    @admin.display(description="Review status", ordering="status")
    def status_label(self, product):
        return product.get_status_display()

    @admin.display(description="Photos", ordering="additional_photo_count")
    def photo_count(self, product):
        return product.additional_photo_count + (1 if product.image else 0)

    @admin.display(description="Main listing photo")
    def main_photo_preview(self, product):
        if not product.image:
            return "No main photo uploaded."
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" alt="Main listing photo" '
            'style="max-width:360px;max-height:280px;object-fit:contain;'
            'background:#f1f3f1;border-radius:8px"></a>',
            product.image.url,
            product.image.url,
        )

    @admin.display(description="Seller account")
    def seller_details(self, product):
        seller = product.seller
        return format_html(
            "<strong>{}</strong><br>Username: {}<br>Email: {}<br>Phone: {}"
            "<br>Seller location: {}, {}",
            seller.get_full_name() or seller.username,
            seller.username,
            seller.email or "Not provided",
            seller.phone_number or "Not provided",
            seller.city or "Not provided",
            seller.get_region_display() or "Not provided",
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["pending_listing_count"] = Product.objects.filter(
            status=Product.Status.PENDING, is_demo=False
        ).count()
        extra_context["open_report_count"] = ListingReport.objects.filter(
            status=ListingReport.Status.OPEN
        ).count()
        return super().changelist_view(request, extra_context=extra_context)

    def response_change(self, request, obj):
        if "_approve_listing" in request.POST:
            try:
                moderation.approve_listing(obj, request.user)
            except moderation.ModerationError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            else:
                self.message_user(request, "Listing approved and published after review.", messages.SUCCESS)
            return HttpResponseRedirect(request.path)

        if "_remove_listing" in request.POST:
            if obj.status != Product.Status.PUBLISHED or obj.is_demo:
                self.message_user(
                    request,
                    "Only a published real listing can be removed from the marketplace.",
                    messages.ERROR,
                )
            else:
                obj.status = Product.Status.DRAFT
                obj.moderation_note = "This listing was removed by an admin."
                obj.save(update_fields=("status", "moderation_note", "updated_at"))
                self.log_change(request, obj, "Listing removed from the public marketplace.")
                self.message_user(
                    request,
                    "Listing removed from public view.",
                    messages.SUCCESS,
                )
            return HttpResponseRedirect(request.path)

        if "_request_changes" in request.POST:
            try:
                moderation.return_listing(obj, request.user, obj.moderation_note)
            except moderation.ModerationError as exc:
                message = str(exc)
                if "short note" in message:
                    message = "Enter a clear note explaining what the seller needs to change."
                self.message_user(request, message, messages.ERROR)
            else:
                self.message_user(request, "Listing returned to the seller with your review note.", messages.WARNING)
            return HttpResponseRedirect(request.path)

        if "_restore_listing" in request.POST:
            was_removed_by_moderation = LogEntry.objects.filter(
                content_type__app_label="marketplace",
                content_type__model="product",
                object_id=str(obj.pk),
                change_message__contains="Listing removed from",
            ).exists()
            if obj.status != Product.Status.DRAFT or not was_removed_by_moderation or obj.is_demo:
                self.message_user(
                    request,
                    "Only a real listing previously removed by moderation can be restored.",
                    messages.ERROR,
                )
            else:
                obj.status = Product.Status.PUBLISHED
                obj.moderation_note = ""
                obj.save(update_fields=("status", "moderation_note", "updated_at"))
                self.log_change(request, obj, "Listing restored to the public marketplace after review.")
                self.message_user(request, "Listing restored to public view.", messages.SUCCESS)
            return HttpResponseRedirect(request.path)

        return super().response_change(request, obj)


@admin.register(ListingReport)
class ListingReportAdmin(admin.ModelAdmin):
    change_list_template = "admin/marketplace/listingreport/change_list.html"
    list_display = ("product", "reporter", "reason", "status", "created_at")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("product__title", "reporter__username", "reporter__email", "details")
    readonly_fields = ("product", "reporter", "reason", "details", "created_at", "updated_at")
    actions = ("mark_reviewed", "dismiss_reports", "remove_reported_listings")
    list_per_page = 25

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["open_report_count"] = ListingReport.objects.filter(
            status=ListingReport.Status.OPEN
        ).count()
        extra_context["pending_listing_count"] = Product.objects.filter(
            status=Product.Status.PENDING, is_demo=False
        ).count()
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product", "reporter")

    @admin.action(description="Mark selected reports as reviewed", permissions=("change",))
    def mark_reviewed(self, request, queryset):
        reports = queryset.filter(status=ListingReport.Status.OPEN)
        updated = 0
        for report in reports.iterator():
            report.status = ListingReport.Status.REVIEWED
            report.save(update_fields=("status", "updated_at"))
            self.log_change(request, report, "Buyer report marked reviewed.")
            updated += 1
        self.message_user(request, f"{updated} report(s) marked reviewed.")

    @admin.action(description="Dismiss selected reports", permissions=("change",))
    def dismiss_reports(self, request, queryset):
        reports = queryset.filter(status=ListingReport.Status.OPEN)
        updated = 0
        for report in reports.iterator():
            report.status = ListingReport.Status.DISMISSED
            report.save(update_fields=("status", "updated_at"))
            self.log_change(request, report, "Buyer report dismissed after review.")
            updated += 1
        self.message_user(request, f"{updated} report(s) dismissed.")

    def has_remove_listing_permission(self, request):
        return request.user.has_perm("marketplace.change_listingreport") and request.user.has_perm(
            "marketplace.change_product")

    @admin.action(description="Remove reported listings from public view", permissions=("remove_listing",))
    def remove_reported_listings(self, request, queryset):
        reports = queryset.filter(
            status=ListingReport.Status.OPEN,
            product__is_demo=False,
        ).select_related("product")
        report_list = list(reports)
        product_ids = {report.product_id for report in report_list}
        products = Product.objects.filter(pk__in=product_ids, status=Product.Status.PUBLISHED)
        updated = 0
        for product in products.iterator():
            product.status = Product.Status.DRAFT
            product.moderation_note = "This listing was removed after a user report."
            product.save(update_fields=("status", "moderation_note", "updated_at"))
            self.log_change(request, product, "Listing removed from public view following buyer report.")
            updated += 1
        for report in report_list:
            report.status = ListingReport.Status.REVIEWED
            report.save(update_fields=("status", "updated_at"))
            self.log_change(request, report, "Report resolved; associated listing removed from public view.")
        self.message_user(
            request,
            f"{updated} reported listing(s) removed from public view.",
            messages.WARNING,
        )


@admin.register(LogEntry)
class MarketplaceAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action_time",
        "user",
        "content_type",
        "object_repr",
        "action_summary",
        "change_summary",
    )
    list_filter = ("action_flag", "content_type", "action_time")
    search_fields = ("user__username", "object_repr", "change_message")
    date_hierarchy = "action_time"
    ordering = ("-action_time",)
    readonly_fields = tuple(field.name for field in LogEntry._meta.fields)
    list_per_page = 50
    verbose_name = "Audit log entry"
    verbose_name_plural = "Audit logs"

    @admin.display(description="Action")
    def action_summary(self, entry):
        if entry.is_addition:
            return "Added"
        if entry.is_deletion:
            return "Deleted"
        return "Changed"

    @admin.display(description="Change details")
    def change_summary(self, entry):
        return entry.change_message or "No change details recorded."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("product", "buyer", "seller", "updated_at")
    search_fields = ("product__title", "buyer__username", "seller__username")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product", "buyer", "seller")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "created_at")
    search_fields = ("body", "sender__username", "conversation__product__title")
    readonly_fields = ("created_at",)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    search_fields = ("user__username", "product__title")
    readonly_fields = ("created_at",)


@admin.register(SellerVerification)
class SellerVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "legal_name", "masked_document_number", "status", "created_at", "reviewed_by")
    list_filter = ("status", "kind")
    search_fields = ("user__username", "user__email", "legal_name", "business_name")
    readonly_fields = ("user", "kind", "legal_name", "document_number", "business_name", "document_link",
                       "created_at", "reviewed_by", "reviewed_at")
    fields = ("user", "kind", "legal_name", "business_name", "document_number", "document_link", "status",
              "reviewer_note", "reviewed_by", "reviewed_at", "created_at")
    actions = ("approve", "reject")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Document")
    def document_link(self, verification):
        url = reverse("verification_document", args=[verification.pk])
        return format_html('<a href="{}" target="_blank" rel="noopener">Open document (staff only)</a>', url)

    def _decide(self, request, verification, status, note=""):
        approve = status == SellerVerification.Status.APPROVED
        moderation.decide_verification(
            verification, request.user, approve,
            note or verification.reviewer_note or "We could not confirm these details. Please resubmit.",
        )

    def save_model(self, request, obj, form, change):
        if change and "status" in form.changed_data and obj.status != SellerVerification.Status.PENDING:
            self._decide(request, obj, obj.status)
        else:
            super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected verifications", permissions=("change",))
    def approve(self, request, queryset):
        for verification in queryset.select_related("user"):
            self._decide(request, verification, SellerVerification.Status.APPROVED)
        self.message_user(request, "Approved. Sellers now show the Verified badge.")

    @admin.action(description="Reject selected verifications", permissions=("change",))
    def reject(self, request, queryset):
        for verification in queryset.select_related("user"):
            self._decide(request, verification, SellerVerification.Status.REJECTED,
                         verification.reviewer_note or "We could not confirm these details. Please resubmit.")
        self.message_user(request, "Rejected. Sellers were notified.")


@admin.register(SellerReview)
class SellerReviewAdmin(admin.ModelAdmin):
    list_display = ("seller", "buyer", "rating", "comment", "is_hidden", "created_at")
    list_filter = ("rating", "is_hidden")
    list_editable = ("is_hidden",)
    search_fields = ("seller__username", "buyer__username", "comment")
    readonly_fields = ("order", "seller", "buyer", "rating", "comment", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = ("reported", "reason", "reporter", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("reported__username", "reporter__username", "details")
    readonly_fields = ("reporter", "reported", "reason", "details", "created_at")
    actions = ("mark_actioned", "dismiss")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Mark selected reports as actioned", permissions=("change",))
    def mark_actioned(self, request, queryset):
        for report in queryset:
            report.status = UserReport.Status.ACTIONED
            report.save(update_fields=("status",))
            self.log_change(request, report, "User report actioned")

    @admin.action(description="Dismiss selected reports", permissions=("change",))
    def dismiss(self, request, queryset):
        for report in queryset:
            report.status = UserReport.Status.DISMISSED
            report.save(update_fields=("status",))
            self.log_change(request, report, "User report dismissed")


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
    search_fields = ("blocker__username", "blocked__username")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProhibitedTerm)
class ProhibitedTermAdmin(admin.ModelAdmin):
    list_display = ("term", "action", "reason", "is_active")
    list_editable = ("action", "is_active")
    list_filter = ("action", "is_active")
    search_fields = ("term",)


@admin.register(SupportRequest)
class SupportRequestAdmin(admin.ModelAdmin):
    list_display = ("subject", "topic", "email", "user", "status", "created_at")
    list_filter = ("status", "topic")
    search_fields = ("subject", "email", "message", "reference")
    readonly_fields = ("user", "email", "topic", "subject", "reference", "message", "created_at")
    fields = ("user", "email", "topic", "subject", "reference", "message", "status", "staff_note", "created_at")

    def has_add_permission(self, request):
        return False



@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("product", "placement", "starts_at", "ends_at", "running", "fee", "created_by")
    list_filter = ("placement", "is_active", "starts_at")
    search_fields = ("product__title", "product__seller__username", "note")
    autocomplete_fields = ("product",)
    readonly_fields = ("created_by", "created_at")
    fields = ("product", "placement", "starts_at", "ends_at", "fee", "note", "is_active", "created_by", "created_at")
    date_hierarchy = "starts_at"

    @admin.display(boolean=True, description="Running now")
    def running(self, promotion):
        return promotion.is_running

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
