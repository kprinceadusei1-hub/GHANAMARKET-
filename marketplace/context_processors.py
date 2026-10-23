from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import Category, GhanaRegion, ListingReport, Product, User


def _category_menu():
    from .catalog import category_menu

    return category_menu()


def marketplace_nav(request):
    """Give every public page the Ghana region list and current search query."""
    match = getattr(request, "resolver_match", None)
    if match and (match.namespace == "admin" or match.url_name in {"marketplace_admin_analytics", "marketplace_admin_search", "marketplace_review_centre"}):
        return {}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        sell_url = reverse("product_create" if user.role == User.Role.SELLER else "become_seller")
    else:
        sell_url = reverse("register")
    cart_count = unread_notifications = unread_messages = 0
    if user and user.is_authenticated:
        from commerce.services import cart_count as count_cart

        cart_count = count_cart(user)
        unread_notifications = user.notifications.filter(is_read=False).count()
        from .models import Conversation, Message

        unread_messages = Message.objects.filter(Conversation.unread_filter(user)).count()
    return {
        "cart_count": cart_count,
        "unread_notifications": unread_notifications,
        "unread_messages": unread_messages,
        "ghana_regions": GhanaRegion.choices,
        "header_region": request.GET.get("region", ""),
        "header_query": request.GET.get("q", ""),
        "nav_categories": Category.objects.filter(parent__isnull=True, is_active=True).values_list("slug", "name"),
        # A callable: templates only build (or read the cached) menu when the menu is rendered.
        "nav_menu": _category_menu,
        "sell_url": sell_url,
    }


def _operations_queues(user):
    """Open trust, support and money queues the staff member is allowed to see."""
    from commerce.models import OrderIssue, Payment, Refund
    from .models import SellerVerification, SupportRequest, UserReport

    definitions = (
        ("marketplace.view_sellerverification", "Seller verifications",
         SellerVerification.objects.filter(status=SellerVerification.Status.PENDING),
         "admin:marketplace_sellerverification_changelist", "?status__exact=pending"),
        ("marketplace.view_userreport", "User reports",
         UserReport.objects.filter(status=UserReport.Status.OPEN),
         "admin:marketplace_userreport_changelist", "?status__exact=open"),
        ("marketplace.view_supportrequest", "Support requests",
         SupportRequest.objects.filter(status=SupportRequest.Status.OPEN),
         "admin:marketplace_supportrequest_changelist", "?status__exact=open"),
        ("commerce.view_orderissue", "Order issues & disputes",
         OrderIssue.objects.filter(status=OrderIssue.Status.OPEN),
         "admin:commerce_orderissue_changelist", "?status__exact=open"),
        ("commerce.view_refund", "Failed refunds",
         Refund.objects.filter(status=Refund.Status.FAILED),
         "admin:commerce_refund_changelist", "?status__exact=failed"),
        ("commerce.view_payment", "Payments needing attention",
         Payment.objects.exclude(failure_reason="").filter(status=Payment.Status.SUCCEEDED)
         | Payment.objects.filter(failure_reason__icontains="mismatch"),
         "admin:commerce_payment_changelist", ""),
    )
    queues = []
    for permission, label, queryset, url_name, query in definitions:
        if user.has_perm(permission):
            queues.append({"label": label, "count": queryset.count(), "url": reverse(url_name) + query})
    return queues


def admin_dashboard(request):
    """Provide permission-aware admin alerts and live overview totals."""
    match = getattr(request, "resolver_match", None)
    user = getattr(request, "user", None)
    is_admin_page = match and (
        match.namespace == "admin" or match.url_name in {"marketplace_admin_analytics", "marketplace_admin_search", "marketplace_review_centre"}
    )
    if not is_admin_page or not user or not user.is_authenticated or not user.is_staff:
        return {}

    can_change_products = user.has_perm("marketplace.change_product")
    can_review = user.has_perm("marketplace.view_product") or can_change_products
    can_view_reports = user.has_perm("marketplace.view_listingreport")
    can_view_users = user.has_perm("marketplace.view_user")
    can_view_conversations = user.has_perm("marketplace.view_conversation")
    dashboard = {
        "admin_dashboard_can_review": can_review,
        "admin_dashboard_can_change_products": can_change_products,
        "admin_dashboard_can_view_reports": can_view_reports,
        "admin_dashboard_can_view_users": can_view_users,
        "admin_dashboard_can_view_conversations": can_view_conversations,
    }

    if can_review:
        dashboard["admin_dashboard_pending"] = Product.objects.filter(
            status=Product.Status.PENDING, is_demo=False
        ).count()
        dashboard["admin_dashboard_products_url"] = reverse("admin:marketplace_product_changelist")
        dashboard["admin_dashboard_pending_url"] = (
            dashboard["admin_dashboard_products_url"] + "?status__exact=pending"
        )
    if can_view_reports:
        dashboard["admin_dashboard_open_reports"] = ListingReport.objects.filter(
            status=ListingReport.Status.OPEN
        ).count()
        dashboard["admin_dashboard_reports_url"] = reverse("admin:marketplace_listingreport_changelist")

    dashboard["admin_dashboard_queues"] = _operations_queues(user)
    from . import control_centre

    cc_queues = control_centre.queue_counts(user)
    dashboard["cc_queues"] = cc_queues
    review_keys = {"seller_requests", "pending_listings", "verifications"}
    review_queues = [queue for queue in cc_queues if queue["key"] in review_keys]
    dashboard["cc_review_total"] = sum(q["count"] for q in review_queues) if review_queues else None
    dashboard["cc_alert_total"] = sum(queue["count"] for queue in cc_queues)
    dashboard["cc_sidebar"] = control_centre.sidebar_groups(user, cc_queues)
    full_path = request.get_full_path()
    for group in dashboard["cc_sidebar"]:
        for link in group["links"]:
            base = link["url"].split("?")[0]
            # Exact match (with filters) wins; otherwise any page inside that model's admin section.
            link["active"] = full_path == link["url"] or (
                "?" not in link["url"] and request.path.startswith(base)
            )
        group["active"] = any(link["active"] for link in group["links"])
    dashboard["cc_can_view_conversations"] = can_view_conversations
    dashboard["cc_can_search"] = any(user.has_perm(p) for p in (
        "marketplace.view_user", "marketplace.view_product", "commerce.view_order"))

    # Compact, live queue counts are available on every admin screen.
    if can_review or can_view_reports or dashboard["admin_dashboard_queues"]:
        dashboard["admin_dashboard_alert_count"] = (
            (dashboard.get("admin_dashboard_pending", 0) if can_change_products else 0)
            + (dashboard.get("admin_dashboard_open_reports", 0) if can_view_reports else 0)
            + sum(queue["count"] for queue in dashboard["admin_dashboard_queues"])
        )

    if match.url_name != "index":
        return dashboard
    dashboard.update(control_centre.build_dashboard(
        user, control_centre.parse_period(request.GET.get("period")), queues=cc_queues,
    ))

    if can_review:
        dashboard.update({
            "admin_dashboard_live": Product.objects.filter(
                status=Product.Status.PUBLISHED, is_demo=False
            ).count(),
            "admin_dashboard_total_listings": Product.objects.filter(is_demo=False).count(),
            "admin_dashboard_rejected": Product.objects.filter(
                status=Product.Status.REJECTED, is_demo=False
            ).count(),
        })
    if can_view_reports:
        dashboard["admin_dashboard_reports_url"] = reverse("admin:marketplace_listingreport_changelist")
    if can_view_users:
        period_start = timezone.localdate() - timedelta(days=29)
        dashboard.update({
            "admin_dashboard_users": User.objects.count(),
            "admin_dashboard_users_url": reverse("admin:marketplace_user_changelist"),
            "admin_dashboard_active_sellers": User.objects.filter(
                role=User.Role.SELLER,
                is_active=True,
                products__status=Product.Status.PUBLISHED,
                products__is_demo=False,
            ).distinct().count(),
            "admin_dashboard_new_users": User.objects.filter(
                date_joined__date__gte=period_start
            ).count(),
        })
    if user.has_perm("commerce.view_order"):
        from django.db.models import Sum
        from commerce.models import Order, Refund

        since = timezone.now() - timedelta(days=30)
        paid = Order.objects.filter(paid_at__gte=since)
        dashboard["admin_dashboard_commerce"] = {
            "paid_orders": paid.count(),
            "paid_value": paid.aggregate(total=Sum("total"))["total"] or 0,
            "awaiting_seller": Order.objects.filter(status=Order.Status.PAID).count(),
            "stale_orders": Order.objects.filter(
                status=Order.Status.PAID, paid_at__lt=timezone.now() - timedelta(days=2)).count(),
            "refunded": Refund.objects.filter(created_at__gte=since).exclude(
                status=Refund.Status.FAILED).aggregate(total=Sum("amount"))["total"] or 0,
        }
    if can_view_conversations:
        from .models import Conversation

        dashboard.update({
            "admin_dashboard_conversations": Conversation.objects.count(),
            "admin_dashboard_conversations_url": reverse("admin:marketplace_conversation_changelist"),
        })
    return dashboard
