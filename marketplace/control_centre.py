"""Data for the admin Control Centre (admin home page and shared admin chrome).

Every figure comes from the database and every section is filtered by the viewer's permissions.
Preview (is_demo) listings are excluded from all metrics. Customer names are shortened to a first
name and initial; no phone numbers, emails or addresses are shown on the dashboard.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .models import (
    Category, ListingReport, Product, SellerVerification, SupportRequest, User, UserReport,
)

PERIODS = ((7, "Last 7 days"), (30, "Last 30 days"), (90, "Last 90 days"))
CHART_COLORS = ("#13804a", "#2563eb", "#c2257a", "#d14b1f", "#f59e0b", "#0f7d8c", "#7c3aed", "#9ca3af")


def parse_period(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 7
    return value if value in dict(PERIODS) else 7


def _url(name, *args, query=""):
    try:
        return reverse(name, args=args) + query
    except NoReverseMatch:
        return ""


def short_name(user):
    """'Ama S.' style display name: enough for staff to recognise, without full personal details."""
    if user is None:
        return "Deleted account"
    first, last = user.first_name.strip(), user.last_name.strip()
    if first:
        return f"{first} {last[:1]}." if last else first
    return user.get_username()


def _change(current, previous):
    """Percentage change, or None when there is no previous value to compare with."""
    if not previous:
        return None
    return round((current - previous) * 100 / previous)


# ---------------------------------------------------------------- sidebar

def sidebar_groups(user, queues):
    """Grouped admin navigation; only links the user may open are included."""
    counts = {queue["key"]: queue["count"] for queue in queues}

    def link(label, perm, url_name, query="", count_key=None):
        if perm and not user.has_perm(perm):
            return None
        url = _url(url_name, query=query)
        return {"label": label, "url": url, "count": counts.get(count_key, 0)} if url else None

    groups = (
        ("Users & Sellers", "users", (
            link("All users", "marketplace.view_user", "admin:marketplace_user_changelist"),
            link("Sellers", "marketplace.view_user", "admin:marketplace_user_changelist", "?role__exact=seller"),
            link("Seller verification", "marketplace.view_sellerverification",
                 "admin:marketplace_sellerverification_changelist", "?status__exact=pending", "verifications"),
            link("Blocked users", "marketplace.view_userblock", "admin:marketplace_userblock_changelist"),
        )),
        ("Listings & Products", "listings", (
            link("All listings", "marketplace.view_product", "admin:marketplace_product_changelist"),
            link("Review queue", "marketplace.view_product", "admin:marketplace_product_changelist",
                 "?status__exact=pending", "pending_listings"),
            link("Search terms", "marketplace.view_searchterm", "admin:marketplace_searchterm_changelist"),
        )),
        ("Orders & Deliveries", "cart", (
            link("Orders", "commerce.view_order", "admin:commerce_order_changelist"),
            link("Awaiting sellers", "commerce.view_order", "admin:commerce_order_changelist",
                 "?status__exact=paid", "pending_orders"),
            link("Checkouts", "commerce.view_checkout", "admin:commerce_checkout_changelist"),
            link("Delivery options", "commerce.view_deliveryoption", "admin:commerce_deliveryoption_changelist"),
        )),
        ("Payments & Finance", "wallet", (
            link("Payments", "commerce.view_payment", "admin:commerce_payment_changelist"),
            link("Refunds", "commerce.view_refund", "admin:commerce_refund_changelist"),
            link("Webhook events", "commerce.view_paymentevent", "admin:commerce_paymentevent_changelist"),
        )),
        ("Reports & Analytics", "chart", (
            link("Marketplace analytics", None, "marketplace_admin_analytics")
            if any(user.has_perm(p) for p in ("marketplace.view_product", "marketplace.view_user",
                                              "marketplace.view_listingreport", "commerce.view_order")) else None,
            link("Listing reports", "marketplace.view_listingreport",
                 "admin:marketplace_listingreport_changelist", "?status__exact=open", "listing_reports"),
            link("User reports", "marketplace.view_userreport",
                 "admin:marketplace_userreport_changelist", "?status__exact=open", "user_reports"),
        )),
        ("Moderation & Safety", "shield", (
            link("Disputes & order issues", "commerce.view_orderissue",
                 "admin:commerce_orderissue_changelist", "?status__exact=open", "disputes"),
            link("Prohibited terms", "marketplace.view_prohibitedterm", "admin:marketplace_prohibitedterm_changelist"),
            link("Seller reviews", "marketplace.view_sellerreview", "admin:marketplace_sellerreview_changelist"),
        )),
        ("Promotions & Advertising", "trending", (
            link("All promotions", "marketplace.view_promotion", "admin:marketplace_promotion_changelist"),
            link("Running now", "marketplace.view_promotion", "admin:marketplace_promotion_changelist",
                 "?is_active__exact=1"),
            link("Promote a listing", "marketplace.add_promotion", "admin:marketplace_promotion_add"),
        )),
        ("Categories", "grid", (
            link("Categories & fields", "marketplace.view_category", "admin:marketplace_category_changelist"),
        )),
        ("Support & Tickets", "support", (
            link("Support requests", "marketplace.view_supportrequest",
                 "admin:marketplace_supportrequest_changelist", "?status__exact=open", "support"),
            link("Conversations", "marketplace.view_conversation", "admin:marketplace_conversation_changelist"),
        )),
        ("Platform Settings", "settings", (
            link("Staff groups & permissions", "auth.view_group", "admin:auth_group_changelist"),
        )),
    )
    result = []
    for label, icon, links in groups:
        links = [item for item in links if item]
        if links:
            result.append({"label": label, "icon": icon, "links": links,
                           "count": sum(item["count"] for item in links)})
    return result


def queue_counts(user):
    """Open work queues for the bell, sidebar badges and quick stats."""
    from commerce.models import Order, OrderIssue

    definitions = (
        ("seller_requests", "Seller requests", "marketplace.view_user",
         lambda: User.objects.filter(role=User.Role.SELLER, seller_status=User.SellerStatus.PENDING).count(),
         "marketplace_review_centre", "?tab=sellers", "user-plus"),
        ("pending_listings", "Listings awaiting review", "marketplace.view_product",
         lambda: Product.objects.filter(status=Product.Status.PENDING, is_demo=False).count(),
         "marketplace_review_centre", "?tab=listings", "listings"),
        ("verifications", "Pending seller verification", "marketplace.view_sellerverification",
         lambda: SellerVerification.objects.filter(status=SellerVerification.Status.PENDING).count(),
         "marketplace_review_centre", "?tab=verifications", "user-check"),
        ("listing_reports", "Reported listings", "marketplace.view_listingreport",
         lambda: ListingReport.objects.filter(status=ListingReport.Status.OPEN).count(),
         "admin:marketplace_listingreport_changelist", "?status__exact=open", "flag"),
        ("user_reports", "Reported users", "marketplace.view_userreport",
         lambda: UserReport.objects.filter(status=UserReport.Status.OPEN).count(),
         "admin:marketplace_userreport_changelist", "?status__exact=open", "flag"),
        ("pending_orders", "Orders awaiting sellers", "commerce.view_order",
         lambda: Order.objects.filter(status=Order.Status.PAID).count(),
         "admin:commerce_order_changelist", "?status__exact=paid", "cart"),
        ("support", "Open support tickets", "marketplace.view_supportrequest",
         lambda: SupportRequest.objects.filter(status=SupportRequest.Status.OPEN).count(),
         "admin:marketplace_supportrequest_changelist", "?status__exact=open", "support"),
        ("disputes", "Disputed orders", "commerce.view_orderissue",
         lambda: OrderIssue.objects.filter(status=OrderIssue.Status.OPEN, kind=OrderIssue.Kind.DISPUTE).count(),
         "admin:commerce_orderissue_changelist", "?status__exact=open&kind__exact=dispute", "alert"),
    )
    return [
        {"key": key, "label": label, "count": count(), "url": _url(url_name, query=query), "icon": icon}
        for key, label, perm, count, url_name, query, icon in definitions
        if user.has_perm(perm)
    ]


# ---------------------------------------------------------------- dashboard

def _kpis(user, start, previous_start):
    from commerce.models import Order

    kpis = []
    if user.has_perm("marketplace.view_user"):
        new_now = User.objects.filter(date_joined__gte=start).count()
        new_before = User.objects.filter(date_joined__gte=previous_start, date_joined__lt=start).count()
        kpis.append({"label": "Total users", "icon": "users", "value": User.objects.filter(is_active=True).count(),
                     "detail": f"{new_now} new", "change": _change(new_now, new_before),
                     "url": _url("admin:marketplace_user_changelist")})
        sellers = User.objects.filter(role=User.Role.SELLER, is_active=True, products__status=Product.Status.PUBLISHED,
                                      products__is_demo=False).distinct().count()
        verified = User.objects.filter(role=User.Role.SELLER, verified_at__isnull=False, is_active=True).count()
        kpis.append({"label": "Active sellers", "icon": "store", "value": sellers,
                     "detail": f"{verified} verified", "change": None,
                     "url": _url("admin:marketplace_user_changelist", query="?role__exact=seller")})
    if user.has_perm("marketplace.view_product"):
        real = Product.objects.filter(is_demo=False)
        added_now = real.filter(created_at__gte=start).count()
        added_before = real.filter(created_at__gte=previous_start, created_at__lt=start).count()
        kpis.append({"label": "Active listings", "icon": "listings",
                     "value": real.filter(status=Product.Status.PUBLISHED).count(),
                     "detail": f"{added_now} submitted", "change": _change(added_now, added_before),
                     "url": _url("admin:marketplace_product_changelist", query="?status__exact=published")})
    if user.has_perm("commerce.view_order"):
        paid = Order.objects.filter(paid_at__isnull=False)
        orders_now = paid.filter(paid_at__gte=start).count()
        orders_before = paid.filter(paid_at__gte=previous_start, paid_at__lt=start).count()
        kpis.append({"label": "Paid orders", "icon": "cart", "value": paid.count(),
                     "detail": f"{orders_now} in period", "change": _change(orders_now, orders_before),
                     "url": _url("admin:commerce_order_changelist", query="?paid_at__isempty=0")})
        value_now = paid.filter(paid_at__gte=start).aggregate(total=Sum("total"))["total"] or Decimal("0")
        value_before = paid.filter(paid_at__gte=previous_start, paid_at__lt=start).aggregate(
            total=Sum("total"))["total"] or Decimal("0")
        kpis.append({"label": "Paid order value", "icon": "money", "value": value_now, "is_money": True,
                     "detail": "Platform fees: none during launch",
                     "change": _change(float(value_now), float(value_before)),
                     "url": _url("marketplace_admin_analytics")})
    return kpis


def _sales_chart(start, days):
    """Daily paid orders and paid value, as SVG-ready points (dual axis)."""
    from commerce.models import Order

    rows = (
        Order.objects.filter(paid_at__date__gte=start)
        .annotate(day=TruncDate("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(orders=Count("pk"), value=Sum("total")).order_by("day")
    )
    by_day = {row["day"]: row for row in rows}
    dates = [start + timedelta(days=i) for i in range(days)]
    orders = [by_day.get(d, {}).get("orders", 0) for d in dates]
    values = [float(by_day.get(d, {}).get("value") or 0) for d in dates]
    if not any(orders):
        return None

    width, height, left, right, top, bottom = 640, 240, 44, 64, 14, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    max_orders = max(max(orders), 1)
    max_value = max(max(values), 1)

    def points(series, peak):
        step = plot_w / max(len(series) - 1, 1)
        return [(round(left + i * step, 1), round(top + plot_h - (v / peak) * plot_h, 1)) for i, v in enumerate(series)]

    order_points = points(orders, max_orders)
    value_points = points(values, max_value)
    label_every = max(1, days // 7)
    return {
        "width": width, "height": height,
        "orders_line": " ".join(f"{x},{y}" for x, y in order_points),
        "orders_area": f"{left},{top + plot_h} " + " ".join(f"{x},{y}" for x, y in order_points)
                       + f" {order_points[-1][0]},{top + plot_h}",
        "value_line": " ".join(f"{x},{y}" for x, y in value_points),
        "grid": [
            {"y": round(top + plot_h - plot_h * f, 1), "orders": round(max_orders * f, 1 if max_orders < 4 else None),
             "value": round(max_value * f)}
            for f in (0, .25, .5, .75, 1)
        ],
        "x_labels": [
            {"x": order_points[i][0], "label": f"{dates[i]:%b} {dates[i].day}"}
            for i in range(0, days, label_every)
        ],
        "points": [
            {"x": order_points[i][0], "y": order_points[i][1],
             "title": f"{dates[i]:%a %d %b}: {orders[i]} paid order(s), GH₵ {values[i]:,.2f}"}
            for i in range(days)
        ],
        "plot_left": left, "plot_right": width - right, "plot_bottom": top + plot_h, "label_y": height - 8,
        "total_orders": sum(orders), "total_value": sum(values),
    }


def _category_donut():
    rows = list(
        Product.objects.filter(status=Product.Status.PUBLISHED, is_demo=False).order_by()
        .values("category__name").annotate(total=Count("id")).order_by("-total")
    )
    total = sum(row["total"] for row in rows)
    if not total:
        return None
    top, rest = rows[:7], rows[7:]
    if rest:
        top.append({"category__name": "Other categories", "total": sum(r["total"] for r in rest)})
    segments, offset = [], 0.0
    for index, row in enumerate(top):
        share = row["total"] * 100 / total
        segments.append({
            "label": row["category__name"], "count": row["total"], "color": CHART_COLORS[index % len(CHART_COLORS)],
            "dash": f"{share:.3f} {100 - share:.3f}", "offset": f"{25 - offset:.3f}",
        })
        offset += share
    return {"total": total, "segments": segments}


def _recent_orders(user):
    from commerce.models import Order

    if not user.has_perm("commerce.view_order"):
        return None
    orders = Order.objects.select_related("buyer").order_by("-created_at")[:6]
    return [{
        "number": order.number, "customer": short_name(order.buyer), "total": order.total,
        "status": order.status, "status_label": order.get_status_display(), "created_at": order.created_at,
        "url": _url("admin:commerce_order_change", order.pk),
    } for order in orders]


def _pending_approvals(user):
    items = []
    if user.has_perm("marketplace.view_user"):
        for member in User.objects.filter(role=User.Role.SELLER, seller_status=User.SellerStatus.PENDING).order_by(
            "-seller_requested_at"
        )[:5]:
            items.append({
                "kind": "seller", "title": "New seller request", "subtitle": short_name(member),
                "meta": ", ".join(filter(None, [member.city, member.region])) or "No location",
                "created_at": member.seller_requested_at or member.date_joined, "image": None,
                "action": "Review", "url": _url("marketplace_review_centre", query=f"?tab=sellers&item={member.pk}"),
            })
    if user.has_perm("marketplace.view_sellerverification"):
        for verification in SellerVerification.objects.filter(
            status=SellerVerification.Status.PENDING
        ).select_related("user")[:5]:
            items.append({
                "kind": "verification", "title": "Seller verification",
                "subtitle": verification.business_name or short_name(verification.user),
                "meta": verification.get_kind_display(), "created_at": verification.created_at, "image": None,
                "action": "Verify",
                "url": _url("marketplace_review_centre", query=f"?tab=verifications&item={verification.pk}"),
            })
    if user.has_perm("marketplace.view_product"):
        for product in Product.objects.filter(status=Product.Status.PENDING, is_demo=False).select_related(
            "category", "seller"
        ).order_by("-updated_at")[:5]:
            items.append({
                "kind": "listing", "title": "Listing review", "subtitle": product.title,
                "meta": f"{product.category.name} · {short_name(product.seller)}"
                        + (" · flagged" if product.risk_flags else ""),
                "created_at": product.updated_at, "image": product.image or None,
                "action": "Review", "url": _url("marketplace_review_centre", query=f"?tab=listings&item={product.pk}"),
            })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:5]


def _recent_activity(user):
    from commerce.models import Payment

    events = []
    if user.has_perm("marketplace.view_user"):
        for member in User.objects.order_by("-date_joined")[:4]:
            events.append({"icon": "user-plus", "title": "New user registered", "detail": short_name(member),
                           "when": member.date_joined, "url": _url("admin:marketplace_user_change", member.pk)})
    if user.has_perm("marketplace.view_product"):
        for product in Product.objects.filter(is_demo=False).order_by("-created_at")[:4]:
            events.append({"icon": "listings", "title": "New listing submitted", "detail": product.title,
                           "when": product.created_at, "url": _url("admin:marketplace_product_change", product.pk)})
    if user.has_perm("commerce.view_payment"):
        for payment in Payment.objects.filter(status=Payment.Status.SUCCEEDED).order_by("-verified_at")[:4]:
            events.append({"icon": "money", "title": "Payment verified",
                           "detail": f"GH₵ {payment.amount:,.2f} · {payment.reference}",
                           "when": payment.verified_at, "url": _url("admin:commerce_payment_change", payment.pk)})
    if user.has_perm("marketplace.view_listingreport"):
        for report in ListingReport.objects.select_related("product").order_by("-created_at")[:4]:
            events.append({"icon": "flag", "title": "Listing reported", "detail": report.get_reason_display(),
                           "when": report.created_at, "url": _url("admin:marketplace_listingreport_change", report.pk)})
    if user.has_perm("admin.view_logentry"):
        verbs = {ADDITION: "Added", CHANGE: "Changed", DELETION: "Deleted"}
        for entry in LogEntry.objects.select_related("user", "content_type").order_by("-action_time")[:5]:
            model = entry.content_type.name if entry.content_type else "record"
            events.append({"icon": "shield", "title": f"{verbs.get(entry.action_flag, 'Updated')} {model}",
                           "detail": f"{entry.object_repr[:60]} · by {short_name(entry.user)}",
                           "when": entry.action_time, "url": _url("admin:admin_logentry_change", entry.pk)})
    events = [event for event in events if event["when"]]
    events.sort(key=lambda event: event["when"], reverse=True)
    return events[:6]


def quick_actions(user):
    actions = (
        ("Manage users", "users", "marketplace.view_user", "admin:marketplace_user_changelist", ""),
        ("Moderate listings", "listings", "marketplace.view_product", "admin:marketplace_product_changelist",
         "?status__exact=pending"),
        ("Process orders", "cart", "commerce.view_order", "admin:commerce_order_changelist", "?status__exact=paid"),
        ("Handle reports", "flag", "marketplace.view_listingreport", "admin:marketplace_listingreport_changelist",
         "?status__exact=open"),
        ("Support tickets", "support", "marketplace.view_supportrequest",
         "admin:marketplace_supportrequest_changelist", "?status__exact=open"),
        ("Categories", "grid", "marketplace.view_category", "admin:marketplace_category_changelist", ""),
        ("Manage promotions", "trending", "marketplace.view_promotion", "admin:marketplace_promotion_changelist", ""),
    )
    return [{"label": label, "icon": icon, "url": _url(url_name, query=query)}
            for label, icon, perm, url_name, query in actions if user.has_perm(perm)]


def build_dashboard(user, period, queues=None):
    today = timezone.localdate()
    start_date = today - timedelta(days=period - 1)
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    previous_start = start - timedelta(days=period)
    queues = queue_counts(user) if queues is None else queues
    return {
        "cc_can_review_centre": any(user.has_perm(perm) for perm in (
            "marketplace.view_user", "marketplace.view_product", "marketplace.view_sellerverification")),
        "cc_period": period,
        "cc_periods": PERIODS,
        "cc_kpis": _kpis(user, start, previous_start),
        "cc_sales": _sales_chart(start_date, period) if user.has_perm("commerce.view_order") else None,
        "cc_can_sales": user.has_perm("commerce.view_order"),
        "cc_categories": _category_donut() if user.has_perm("marketplace.view_product") else None,
        "cc_can_categories": user.has_perm("marketplace.view_product"),
        "cc_quick_stats": [q for q in queues if q["key"] != "user_reports"],
        "cc_recent_orders": _recent_orders(user),
        "cc_approvals": _pending_approvals(user),
        "cc_can_approve": user.has_perm("marketplace.view_product") or user.has_perm("marketplace.view_sellerverification"),
        "cc_activity": _recent_activity(user),
        "cc_quick_actions": quick_actions(user),
        "cc_demo_count": Product.objects.filter(is_demo=True).count(),
        "cc_category_count": Category.objects.filter(parent__isnull=True, is_active=True).count(),
    }
