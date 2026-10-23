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


VERIFY_REASONS = (
    "The photo of the card is blurry or cut off. Please upload a clear photo of the whole front.",
    "The name on the card does not match the name you typed.",
    "The card number does not match the card in the photo.",
    "We could not confirm this document. Please upload your Ghana Card (not another ID).",
)
SELLER_REASONS = (
    "Please add your Ghana Card details so we can confirm who you are.",
    "Please add a working Ghana phone number.",
    "Please add your real town and region.",
)


def _name_tokens(text):
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text or "").split() if len(token) > 1}


def id_check(verification):
    """Everything an admin needs to verify an ID at a glance, with automatic warning signs.

    Signals are hints for the reviewer, never automatic decisions.
    """
    from .forms import normalise_ghana_card

    user = verification.user
    signals = []
    if verification.kind == SellerVerification.Kind.GHANA_CARD:
        valid = normalise_ghana_card(verification.document_number) == verification.document_number
        signals.append(("ok" if valid else "bad",
                        "Ghana Card number format is valid" if valid else "Card number is not in the GHA-123456789-0 format"))
    others = SellerVerification.objects.filter(document_number__iexact=verification.document_number).exclude(
        user=user).exclude(status=SellerVerification.Status.REJECTED).select_related("user")
    if others:
        names = ", ".join(f"@{other.user.username}" for other in others[:3])
        signals.append(("bad", f"Same card number already used by {names}"))
    else:
        signals.append(("ok", "Card number is not used by any other account"))
    account, document = _name_tokens(user.get_full_name()), _name_tokens(verification.legal_name)
    if not account:
        signals.append(("warn", "The account has no full name to compare with"))
    elif account <= document or document <= account:
        signals.append(("ok", "Name on card matches the account name"))
    elif account & document:
        signals.append(("warn", f"Name only partly matches the account ({user.get_full_name()})"))
    else:
        signals.append(("bad", f"Name on card differs from the account ({user.get_full_name()})"))
    signals.append(("ok", "Account has a Ghana phone number") if user.whatsapp_number
                   else ("warn", "Account has no valid Ghana phone number"))
    earlier = user.verifications.filter(status=SellerVerification.Status.REJECTED).exclude(pk=verification.pk).count()
    if earlier:
        signals.append(("warn", f"{earlier} earlier submission{'s were' if earlier > 1 else ' was'} not approved"))
    name = verification.document.name.lower()
    return {
        "pk": verification.pk,
        "url": reverse("verification_document", args=[verification.pk]),
        "is_image": name.endswith((".jpg", ".jpeg", ".png", ".webp")),
        "kind": verification.get_kind_display(),
        "status": verification.get_status_display(),
        "is_pending": verification.status == SellerVerification.Status.PENDING,
        "legal_name": verification.legal_name,
        "number": verification.document_number,
        "business_name": verification.business_name,
        "submitted": verification.created_at,
        "signals": signals,
        "warnings": sum(1 for level, _ in signals if level != "ok"),
    }


def _detail(kind, obj, user=None):
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
                "The Ghana Card above is clear and belongs to this person.",
                "The name and phone number look genuine.",
                "The location is a real place in Ghana.",
                "There are no reports or earlier warnings about this person.",
            ],
            "reject_label": "Do not approve",
            "admin_url": reverse("admin:marketplace_user_change", args=[obj.pk]),
            "id_check": id_check(obj.verifications.first()) if obj.verifications.exists() and (
                user is None or user.has_perm("marketplace.view_sellerverification")) else None,
            "reasons": SELLER_REASONS,
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
            ("Account", f"{obj.user.get_full_name() or obj.user.username} (@{obj.user.username})"),
            ("Seller status", obj.user.get_seller_status_display() if obj.user.role == User.Role.SELLER else "Buyer"),
            ("Phone", obj.user.phone_number or "—"),
            ("Location", ", ".join(filter(None, [obj.user.city, obj.user.region])) or "—"),
        ],
        "id_check": id_check(obj),
        "reasons": VERIFY_REASONS,
        "checks": [
            "The card photo is clear, complete and not edited.",
            "The name and number on the document match what was typed.",
            "The name matches the seller's account.",
        ],
        "reject_label": "Do not approve",
        "admin_url": reverse("admin:marketplace_sellerverification_change", args=[obj.pk]),
    }


def _decide(kind, obj, staff, approve, note, also_verify=False):
    if kind == "sellers":
        if not approve:
            return moderation.reject_seller(obj, staff, note)
        moderation.approve_seller(obj, staff)
        card = obj.verifications.filter(status=SellerVerification.Status.PENDING).first()
        if also_verify and card and staff.has_perm("marketplace.change_sellerverification"):
            moderation.decide_verification(card, staff, True)
        return None
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
            _decide(kind, obj, request.user, approve, request.POST.get("note", ""),
                    also_verify=request.POST.get("also_verify") == "1")
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
        "detail": _detail(kind, selected, request.user) if selected else None,
    })
