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
