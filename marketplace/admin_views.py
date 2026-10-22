from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from .models import Category, GhanaRegion, ListingReport, Product, User


PERIOD_OPTIONS = ((7, "7 days"), (30, "30 days"), (90, "90 days"))


def _daily_series(queryset, date_field, start, end):
    rows = (
        queryset.filter(**{f"{date_field}__date__range": (start, end)})
        .annotate(day=TruncDate(date_field, tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(total=Count("pk"))
        .order_by("day")
    )
    counts = {row["day"]: row["total"] for row in rows}
    days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    peak = max((counts.get(day, 0) for day in days), default=0)
    label_step = max(1, len(days) // 6)
    return [
        {
            "label": day.strftime("%b %d").replace(" 0", " "),
            "count": counts.get(day, 0),
            "height": round(counts.get(day, 0) * 100 / peak) if peak else 0,
            "show_label": index % label_step == 0 or index == len(days) - 1,
        }
        for index, day in enumerate(days)
    ]


def marketplace_analytics(request):
    """Read-only analytics based on actual, non-demo marketplace records."""
    can_view_products = (
        request.user.has_perm("marketplace.view_product")
        or request.user.has_perm("marketplace.change_product")
    )
    can_view_users = request.user.has_perm("marketplace.view_user")
    can_view_reports = request.user.has_perm("marketplace.view_listingreport")
    can_view_orders = request.user.has_perm("commerce.view_order")
    if not (can_view_products or can_view_users or can_view_reports or can_view_orders):
        raise PermissionDenied

    try:
        period = int(request.GET.get("period", "30"))
    except (TypeError, ValueError):
        period = 30
    if period not in {option[0] for option in PERIOD_OPTIONS}:
        period = 30

    end = timezone.localdate()
    start = end - timedelta(days=period - 1)
    context = {
        **admin.site.each_context(request),
        "title": "Marketplace analytics",
        "period": period,
        "period_options": PERIOD_OPTIONS,
        "start_date": start,
        "end_date": end,
        "can_view_products": can_view_products,
        "can_view_users": can_view_users,
        "can_view_reports": can_view_reports,
        "can_view_orders": can_view_orders,
    }

    products = Product.objects.filter(is_demo=False)
    if can_view_products:
        category_counts = {
            row["category"]: row["total"]
            for row in products.values("category").annotate(total=Count("pk"))
        }
        region_counts = {
            row["region"]: row["total"]
            for row in products.values("region").annotate(total=Count("pk"))
        }
        category_max = max(category_counts.values(), default=0)
        region_max = max(region_counts.values(), default=0)
        listing_series = _daily_series(products, "created_at", start, end)
        context.update({
            "listing_total": products.count(),
            "listing_live": products.filter(status=Product.Status.PUBLISHED).count(),
            "listing_inactive": products.exclude(status=Product.Status.PUBLISHED).count(),
            "listing_pending": products.filter(status=Product.Status.PENDING).count(),
            "listing_series": listing_series,
            "listing_activity_total": sum(point["count"] for point in listing_series),
            "category_data": [
                {
                    "label": label,
                    "count": category_counts.get(value, 0),
                    "percent": round(category_counts.get(value, 0) * 100 / category_max) if category_max else 0,
                }
                for value, label in Category.objects.filter(parent__isnull=True).values_list("slug", "name")
            ],
            "region_data": [
                {
                    "label": label,
                    "count": region_counts.get(value, 0),
                    "percent": round(region_counts.get(value, 0) * 100 / region_max) if region_max else 0,
                }
                for value, label in GhanaRegion.choices
            ],
        })
    if can_view_users:
        user_series = _daily_series(User.objects.all(), "date_joined", start, end)
        context.update({
            "user_total": User.objects.count(),
            "seller_total": User.objects.filter(role=User.Role.SELLER, is_active=True).count(),
            "user_series": user_series,
            "registration_activity_total": sum(point["count"] for point in user_series),
        })
    if can_view_reports:
        context["open_report_total"] = ListingReport.objects.filter(
            status=ListingReport.Status.OPEN
        ).count()
        report_series = _daily_series(ListingReport.objects.all(), "created_at", start, end)
        context.update({
            "report_series": report_series,
            "report_activity_total": sum(point["count"] for point in report_series),
        })

    if can_view_orders:
        context.update(_commerce_analytics(start, end))

    return render(request, "admin/marketplace/analytics.html", context)


def _commerce_analytics(start, end):
    """Sales figures from orders whose payment was verified with the provider."""
    from commerce.models import Order, Payment, Refund

    paid = Order.objects.filter(paid_at__date__range=(start, end))
    paid_value = paid.aggregate(total=Sum("total"))["total"] or Decimal("0")
    paid_count = paid.count()
    attempts = Payment.objects.filter(created_at__date__range=(start, end))
    succeeded = attempts.filter(status=Payment.Status.SUCCEEDED).count()
    failed = attempts.filter(status=Payment.Status.FAILED).count()
    refunded = Refund.objects.filter(created_at__date__range=(start, end)).exclude(
        status=Refund.Status.FAILED).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    order_series = _daily_series(Order.objects.exclude(paid_at__isnull=True), "paid_at", start, end)
    status_counts = dict(paid.values_list("status").annotate(total=Count("pk")).values_list("status", "total"))
    status_max = max(status_counts.values(), default=0)
    channel_counts = attempts.filter(status=Payment.Status.SUCCEEDED).exclude(channel="").values(
        "channel").annotate(total=Count("pk")).order_by("-total")
    return {
        "order_paid_count": paid_count,
        "order_paid_value": paid_value,
        "order_average_value": (paid_value / paid_count) if paid_count else Decimal("0"),
        "order_refunded_value": refunded,
        "payment_success_rate": round(succeeded * 100 / (succeeded + failed)) if (succeeded + failed) else None,
        "order_series": order_series,
        "order_activity_total": sum(point["count"] for point in order_series),
        "order_status_data": [
            {"label": label, "count": status_counts.get(value, 0),
             "percent": round(status_counts.get(value, 0) * 100 / status_max) if status_max else 0}
            for value, label in Order.Status.choices if value != Order.Status.PENDING_PAYMENT
        ],
        "payment_channels": list(channel_counts),
    }


SEARCH_LIMIT = 8


def marketplace_search(request):
    """Staff-wide search across users, listings and orders, limited to what the viewer may see."""
    from django.db.models import Q
    from django.urls import reverse

    from commerce.models import Order
    from .control_centre import short_name

    query = " ".join(request.GET.get("q", "").split())[:80]
    groups = []
    if len(query) >= 2:
        if request.user.has_perm("marketplace.view_user"):
            users = User.objects.filter(
                Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
                | Q(email__iexact=query)
            ).order_by("-date_joined")[:SEARCH_LIMIT]
            groups.append(("Users & sellers", [
                {"title": short_name(u), "meta": f"@{u.username} · {u.get_role_display()}"
                 + (" · verified" if u.verified_at else "") + ("" if u.is_active else " · suspended"),
                 "url": reverse("admin:marketplace_user_change", args=[u.pk])} for u in users
            ]))
        if request.user.has_perm("marketplace.view_product"):
            listing_filter = Q(title__icontains=query) | Q(brand__icontains=query)
            if query.lstrip("#").isdigit():
                listing_filter |= Q(pk=int(query.lstrip("#")))  # "#14" finds ad ID 14
            products = Product.objects.filter(listing_filter).select_related("category").order_by(
                "-updated_at")[:SEARCH_LIMIT]
            groups.append(("Listings", [
                {"title": p.title, "meta": f"#{p.pk} · {p.category.name} · {p.get_status_display()}"
                 + (" · preview" if p.is_demo else ""),
                 "url": reverse("admin:marketplace_product_change", args=[p.pk])} for p in products
            ]))
        if request.user.has_perm("commerce.view_order"):
            orders = Order.objects.filter(
                Q(number__icontains=query) | Q(checkout__reference__icontains=query)
            ).select_related("buyer").order_by("-created_at")[:SEARCH_LIMIT]
            groups.append(("Orders", [
                {"title": o.number, "meta": f"{short_name(o.buyer)} · GH₵ {o.total:,.2f} · {o.get_status_display()}",
                 "url": reverse("admin:commerce_order_change", args=[o.pk])} for o in orders
            ]))
    if not any(request.user.has_perm(p) for p in ("marketplace.view_user", "marketplace.view_product", "commerce.view_order")):
        raise PermissionDenied
    return render(request, "admin/marketplace/search.html", {
        **admin.site.each_context(request),
        "title": "Search",
        "query": query,
        "groups": groups,
        "result_total": sum(len(items) for _, items in groups),
    })



def marketplace_pulse(request):
    """Live queue counts for the Control Centre (polled by the dashboard; same permissions as the page)."""
    from django.http import JsonResponse
    from django.utils import timezone

    from .control_centre import queue_counts

    queues = queue_counts(request.user)
    response = JsonResponse({
        "total": sum(queue["count"] for queue in queues),
        "queues": {queue["key"]: queue["count"] for queue in queues},
        "checked_at": timezone.localtime().strftime("%H:%M"),
    })
    response["Cache-Control"] = "no-store"
    return response



def delete_previews(request):
    """Remove the preview catalogue from the Control Centre (superusers only; recorded in the audit log)."""
    from django.contrib import messages
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType
    from django.shortcuts import redirect

    from .management.commands.seed_demo_marketplace import delete_preview_catalogue

    if request.method != "POST" or not request.user.is_superuser:
        raise PermissionDenied
    count = delete_preview_catalogue()
    LogEntry.objects.log_action(
        user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(Product).pk,
        object_id="", object_repr=f"{count} preview listings", action_flag=DELETION,
        change_message="Removed the preview catalogue from the public site.",
    )
    messages.success(request, f"Removed {count} preview listings. Only real ads are shown now.")
    return redirect("admin:index")
