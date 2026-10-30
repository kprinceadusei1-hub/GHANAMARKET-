from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def ago(value):
    """Compact age such as "just now", "5m ago", "3h ago", "2d ago" or "12 Oct"."""
    if not value:
        return ""
    seconds = int((timezone.now() - value).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 86400 * 7:
        return f"{seconds // 86400}d ago"
    local = timezone.localtime(value)
    if local.year == timezone.localtime().year:
        return f"{local.day} {local:%b}"
    return f"{local.day} {local:%b %Y}"


@register.filter
def cedis(value):
    """Format a price as GH₵ with grouping, dropping .00 for whole amounts."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value
    if amount == int(amount):
        return f"GH₵ {int(amount):,}"
    return f"GH₵ {amount:,.2f}"


@register.filter
def thumbnail(image_field, width=480):
    """Small JPEG for listing cards; see marketplace.images.thumbnail_url."""
    from marketplace.images import thumbnail_url

    return thumbnail_url(image_field, int(width))


@register.inclusion_tag("partials/towns_datalist.html")
def ghana_towns_datalist():
    from marketplace.ghana_places import town_options

    return {"towns": town_options()}


@register.filter
def place(obj):
    """'Town, Region' for a user or listing; whichever parts are filled in."""
    city, region = (getattr(obj, "city", "") or "").strip(), (getattr(obj, "region", "") or "").strip()
    if city.lower() == region.lower():
        city = ""
    elif city.islower():
        city = city.title()
    return ", ".join(part for part in (city, region) if part)


@register.filter
def tidy_caps(value):
    """Show ALL-CAPS seller text ('18 PRO MAX') as '18 Pro Max'; leave normal text alone."""
    text = str(value or "")
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) > 3 and all(ch.isupper() for ch in letters):
        return " ".join(word if len(word) <= 3 and word.isalpha() and word in {"TV", "USB", "HD", "SSD", "RAM", "GB", "TB", "4K", "LED", "AC"} else word.capitalize() for word in text.split(" "))
    return text


@register.filter
def with_error_aria(field):
    """Render an invalid field so screen readers announce its error message."""
    attrs = field.field.widget.attrs
    described = " ".join(filter(None, [attrs.get("aria-describedby", ""), f"{field.auto_id}_errors"]))
    return field.as_widget(attrs={"aria-invalid": "true", "aria-describedby": described})


CHECKOUT_STEPS = ((1, "Cart"), (2, "Delivery"), (3, "Payment"), (4, "Done"))


@register.inclusion_tag("commerce/_steps.html")
def checkout_steps(current):
    """Progress indicator shown on the cart, checkout and payment pages."""
    return {"steps": CHECKOUT_STEPS, "current": current}


@register.inclusion_tag("partials/account_nav.html", takes_context=True)
def account_nav(context):
    """Left-hand navigation shared by every account page; links only to pages that exist."""
    from django.urls import reverse

    request = context["request"]
    user = request.user
    current = request.resolver_match.view_name if request.resolver_match else ""
    is_seller = user.role == "seller"

    def item(label, icon, view_name, count=0, also=()):
        return {"label": label, "icon": icon, "url": reverse(view_name), "count": count,
                "active": current == view_name or current in also}

    sections = [{"title": "Shopping", "items": [
        item("Overview", "dashboard", "account_overview"),
        item("My orders", "package", "commerce:order_list", also=("commerce:order_detail",)),
        item("Saved items", "heart", "saved_listings"),
        item("Messages", "chat", "conversation_list", context.get("unread_messages", 0)),
        item("Notifications", "bell", "notification_list", context.get("unread_notifications", 0)),
        item("Addresses", "pin", "commerce:addresses"),
    ]}]
    if is_seller:
        to_fulfil = user.seller_orders.filter(status__in=("paid", "processing")).count()
        sections.append({"title": "Selling", "items": [
            item("My listings", "listings", "seller_listings", also=("product_update",)),
            item("Post an ad", "plus", "product_create"),
            item("Orders to fulfil", "truck", "commerce:seller_orders", to_fulfil, also=("commerce:seller_order_detail",)),
            item("Storefront", "store", "storefront_settings"),
            item("Verification", "user-check", "seller_verification"),
        ]})
    sections.append({"title": "Account", "items": [
        item("Settings", "settings", "account_settings"),
        item("Password", "lock", "password_change"),
    ]})
    return {"user": user, "is_seller": is_seller, "sections": sections}
