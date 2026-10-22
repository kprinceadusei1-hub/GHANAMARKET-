"""Review Centre: one admin page to review and decide seller requests, listings and verification badges.

Left: everything waiting, oldest first. Right: the full details of the selected item with Approve and
Reject buttons. Decisions go through ``marketplace.moderation`` so they are logged and notified.
"""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

from . import moderation
from .models import ListingReport, Product, SellerVerification, User, UserReport

TABS = (
    # key, label, view permission, decide permission
    ("sellers", "Seller requests", "marketplace.view_user", "marketplace.change_user"),
    ("listings", "Listings", "marketplace.view_product", "marketplace.change_product"),
    ("verifications", "Verification badges", "marketplace.view_sellerverification",
     "marketplace.change_sellerverification"),
)
PAGE_LIMIT = 100


def pending(kind):
    if kind == "sellers":
        return User.objects.filter(role=User.Role.SELLER, seller_status=User.SellerStatus.PENDING).order_by(
            "seller_requested_at", "date_joined")
    if kind == "listings":
        return Product.objects.filter(status=Product.Status.PENDING, is_demo=False).select_related(
            "seller", "category", "subcategory").order_by("updated_at")
    return SellerVerification.objects.filter(status=SellerVerification.Status.PENDING).select_related(
        "user").order_by("created_at")


def _row(kind, obj):
    """Compact summary for the left-hand list."""
    if kind == "sellers":
        return {"title": obj.get_full_name() or obj.username,
                "meta": ", ".join(filter(None, [obj.city, obj.region])) or "No location",
                "when": obj.seller_requested_at or obj.date_joined, "image": None, "icon": "user-plus"}
    if kind == "listings":
        return {"title": obj.title, "meta": f"GH₵ {obj.price:,.0f} · {obj.category.name}",
                "when": obj.updated_at, "image": obj.image or None, "icon": "listings",
                "flagged": bool(obj.risk_flags)}
    return {"title": obj.business_name or obj.legal_name, "meta": obj.get_kind_display(),
            "when": obj.created_at, "image": None, "icon": "user-check"}


def _detail(kind, obj):
    """Facts an admin needs before deciding. Staff-only page, so contact details are shown."""
    if kind == "sellers":
        return {
            "title": obj.get_full_name() or obj.username,
            "subtitle": f"@{obj.username} wants to sell on GhanaMarket",
            "facts": [
                ("Email", obj.email), ("Phone", obj.phone_number or "—"),
                ("Location", ", ".join(filter(None, [obj.city, obj.region])) or "—"),
                ("Joined", obj.date_joined), ("Requested", obj.seller_requested_at or obj.date_joined),
                ("Reports against this person", UserReport.objects.filter(reported=obj).count()),
                ("Earlier decision note", obj.seller_review_note or "—"),
            ],
            "checks": [
                "The name and phone number look genuine.",
                "The location is a real place in Ghana.",
                "There are no reports or earlier warnings about this person.",
            ],
            "reject_label": "Do not approve",
            "admin_url": reverse("admin:marketplace_user_change", args=[obj.pk]),
        }
    if kind == "listings":
        photos = ([obj.image] if obj.image else []) + [photo.image for photo in obj.photos.all()]
        selling = [label for flag, label in ((obj.allows_checkout, "online checkout"),
                                             (obj.allows_direct_contact, "chat")) if flag]
        return {
            "title": obj.title,
            "subtitle": f"GH₵ {obj.price:,.2f}" + (" · negotiable" if obj.price_negotiable else ""),
            "photos": photos,
            "description": obj.description,
            "risk_flags": [flag.strip() for flag in obj.risk_flags.split(";") if flag.strip()],
            "facts": [
                ("Category", obj.category_label), ("Condition", obj.get_condition_display()),
                *obj.attribute_items(),
                ("Location", f"{obj.city}, {obj.region}" if obj.region else obj.city),
                ("Buyers can", " and ".join(selling) or "—"),
                ("Seller", f"{obj.seller.get_full_name() or obj.seller.username} (@{obj.seller.username})"),
                ("Seller account", obj.seller.get_seller_status_display()
                 + (" · verified" if obj.seller.verified_at else "")),
                ("Seller's live ads", Product.objects.filter(
                    seller=obj.seller, status=Product.Status.PUBLISHED, is_demo=False).count()),
                ("Reports on this ad", ListingReport.objects.filter(product=obj).count()),
                ("Last edited", obj.updated_at),
            ],
            "checks": [
                "The photos show the real item and match the title.",
                "The price is realistic, with no signs of a scam.",
                "The item is allowed and in the right category.",
            ],
            "seller_blocked": not obj.seller.can_sell,
            "reject_label": "Return to seller",
            "admin_url": reverse("admin:marketplace_product_change", args=[obj.pk]),
        }
    return {
        "title": obj.business_name or obj.legal_name,
        "subtitle": f"{obj.get_kind_display()} for @{obj.user.username}",
        "facts": [
            ("Legal name on document", obj.legal_name), ("Business name", obj.business_name or "—"),
            ("Document number", obj.document_number),
            ("Account name", obj.user.get_full_name() or obj.user.username),
            ("Submitted", obj.created_at),
        ],
        "document_url": reverse("verification_document", args=[obj.pk]),
        "checks": [
            "Open the document: it is clear, complete and not edited.",
            "The name and number on the document match what was typed.",
            "The name matches the seller's account.",
        ],
        "reject_label": "Do not approve",
        "admin_url": reverse("admin:marketplace_sellerverification_change", args=[obj.pk]),
    }


def _decide(kind, obj, staff, approve, note):
    if kind == "sellers":
        return moderation.approve_seller(obj, staff) if approve else moderation.reject_seller(obj, staff, note)
    if kind == "listings":
        return moderation.approve_listing(obj, staff) if approve else moderation.return_listing(obj, staff, note)
    if not approve and not (note or "").strip():
        raise moderation.ModerationError("Write a short note telling the person what to fix.")
    return moderation.decide_verification(obj, staff, approve, note)


def review_centre(request):
    tabs = [
        {"key": key, "label": label, "can_decide": request.user.has_perm(decide), "count": pending(key).count()}
        for key, label, view, decide in TABS if request.user.has_perm(view)
    ]
    if not tabs:
        raise PermissionDenied
    keys = [tab["key"] for tab in tabs]
    kind = request.POST.get("kind") if request.method == "POST" else request.GET.get("tab")
    if kind not in keys:
        kind = next((tab["key"] for tab in tabs if tab["count"]), keys[0])
    tab = next(t for t in tabs if t["key"] == kind)

    if request.method == "POST":
        if not tab["can_decide"]:
            raise PermissionDenied
        obj = pending(kind).filter(pk=request.POST.get("pk")).first()
        if obj is None:
            messages.warning(request, "That item was already decided, possibly by another admin.")
            return redirect(f"{request.path}?tab={kind}")
        approve = request.POST.get("decision") == "approve"
        try:
            _decide(kind, obj, request.user, approve, request.POST.get("note", ""))
        except moderation.ModerationError as exc:
            messages.error(request, str(exc))
            return redirect(f"{request.path}?tab={kind}&item={obj.pk}")
        outcome = "approved" if approve else "sent back with your note"
        messages.success(request, f"“{obj}” {outcome}. Showing the next item.")
        return redirect(f"{request.path}?tab={kind}")

    objects = list(pending(kind)[:PAGE_LIMIT])
    wanted = request.GET.get("item")
    selected = next((obj for obj in objects if str(obj.pk) == wanted), None) or (objects[0] if objects else None)
    return render(request, "admin/marketplace/review_centre.html", {
        **admin.site.each_context(request),
        "title": "Review Centre",
        "tabs": tabs,
        "tab": tab,
        "rows": [{"pk": obj.pk, "selected": obj is selected, **_row(kind, obj)} for obj in objects],
        "selected": selected,
        "detail": _detail(kind, selected) if selected else None,
    })
