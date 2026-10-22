"""Catalogue queries shared by the storefront views: categories, search and attribute filters."""
from decimal import Decimal, InvalidOperation

from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When

from .models import Category, CategoryAttribute, Product, Promotion

SEARCH_FIELDS = ("title", "brand", "model", "description", "city", "region")
MAX_SEARCH_TERMS = 6


def published_products():
    return Product.objects.filter(
        status=Product.Status.PUBLISHED, is_demo=False
    ).select_related("seller", "category", "subcategory")


def showcase_products():
    """What buyers browse: real published listings plus the clearly labelled preview catalogue.

    Previews stay visible until the owner deletes them (``seed_demo_marketplace --delete``).
    Real listings always come first: views order by ``is_demo`` before anything else.
    """
    return Product.objects.filter(status=Product.Status.PUBLISHED).select_related(
        "seller", "category", "subcategory"
    ).order_by("is_demo", "-created_at")


def top_categories():
    return Category.objects.filter(parent__isnull=True, is_active=True)


def categories_with_counts():
    """Active top-level categories with their live listing counts, as template-friendly dicts."""
    counts = {
        row["category"]: row["total"]
        for row in showcase_products().order_by().values("category").annotate(total=Count("id"))
    }
    return [
        {
            "value": category.slug,
            "label": category.name,
            "icon": category.icon_key,
            "count": counts.get(category.slug, 0),
        }
        for category in top_categories()
    ]


def search_terms(query):
    return [term for term in query.split() if term][:MAX_SEARCH_TERMS]


def apply_search(queryset, query):
    """Every word must match some listing field; results get a relevance score for sorting."""
    terms = search_terms(query)
    for term in terms:
        term_filter = Q()
        for field in SEARCH_FIELDS:
            term_filter |= Q(**{f"{field}__icontains": term})
        term_filter |= Q(category__name__icontains=term) | Q(subcategory__name__icontains=term)
        queryset = queryset.filter(term_filter)
    if not terms:
        return queryset
    phrase = " ".join(terms)
    return queryset.annotate(relevance=Case(
        When(title__iexact=phrase, then=Value(100)),
        When(title__istartswith=phrase, then=Value(60)),
        When(title__icontains=phrase, then=Value(40)),
        When(Q(brand__icontains=phrase) | Q(model__icontains=phrase), then=Value(20)),
        default=Value(0),
        output_field=IntegerField(),
    ))


def parse_decimal(raw):
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() and value >= 0 else None


def attribute_filters(category, params):
    """Build filter widgets for a category's filterable attributes and the matching queryset filter.

    Returns (widgets, q_filter, active) where ``widgets`` describe the controls to render and
    ``active`` lists (label, display value, param names) for the active-filter chips.
    """
    widgets, active, q_filter = [], [], Q()
    if category is None:
        return widgets, q_filter, active
    for definition in category.attribute_definitions().filter(is_filterable=True):
        lookup = f"attributes__{definition.key}"
        param = f"a_{definition.key}"
        widget = {"definition": definition, "param": param}
        if definition.kind == CategoryAttribute.Kind.NUMBER:
            minimum, maximum = parse_decimal(params.get(f"{param}_min")), parse_decimal(params.get(f"{param}_max"))
            widget.update(min_param=f"{param}_min", max_param=f"{param}_max",
                          min_value=params.get(f"{param}_min", ""), max_value=params.get(f"{param}_max", ""))
            if minimum is not None:
                q_filter &= Q(**{f"{lookup}__gte": float(minimum)})
                active.append((definition.label, f"from {minimum}", (f"{param}_min",)))
            if maximum is not None:
                q_filter &= Q(**{f"{lookup}__lte": float(maximum)})
                active.append((definition.label, f"up to {maximum}", (f"{param}_max",)))
        elif definition.kind == CategoryAttribute.Kind.BOOLEAN:
            value = params.get(param, "")
            widget["value"] = value
            if value in {"yes", "no"}:
                q_filter &= Q(**{lookup: value == "yes"})
                active.append((definition.label, "Yes" if value == "yes" else "No", (param,)))
        elif definition.kind == CategoryAttribute.Kind.CHOICE:
            value = params.get(param, "")
            widget["value"] = value
            if value in definition.choice_list:
                q_filter &= Q(**{lookup: value})
                active.append((definition.label, value, (param,)))
        else:
            value = params.get(param, "").strip()[:60]
            widget["value"] = value
            if value:
                q_filter &= Q(**{f"{lookup}__icontains": value})
                active.append((definition.label, value, (param,)))
        widgets.append(widget)
    return widgets, q_filter, active


def _nice(value):
    """Round a price boundary to a friendly figure (e.g. 1 234 -> 1 200, 68 412 -> 68 000)."""
    value = int(value)
    if value < 100:
        return value
    step = 10 ** (len(str(value)) - 2)
    return max(step, round(value / step) * step)


def price_buckets(queryset, count=4):
    """Quick price ranges that split the current results into roughly equal groups.

    Returns [{'label', 'min', 'max'}]; empty when there are too few listings to be useful.
    """
    prices = sorted(queryset.order_by().values_list("price", flat=True)[:2000])
    if len(prices) < count * 2:
        return []
    edges = sorted({_nice(prices[len(prices) * i // count]) for i in range(1, count)})
    if len(edges) < 2:
        return []

    def short(amount):
        return f"{amount / 1000:g} K" if amount >= 1000 else f"{amount:g}"

    buckets = [{"label": f"Under GH₵ {short(edges[0])}", "min": "", "max": edges[0]}]
    for low, high in zip(edges, edges[1:]):
        buckets.append({"label": f"GH₵ {short(low)} – {short(high)}", "min": low, "max": high})
    buckets.append({"label": f"Over GH₵ {short(edges[-1])}", "min": edges[-1], "max": ""})
    return buckets


def choice_facet(queryset, category, limit=8):
    """Option tiles with counts for the category's first filterable choice attribute (e.g. car make)."""
    if category is None:
        return None
    definition = category.attribute_definitions().filter(
        is_filterable=True, kind=CategoryAttribute.Kind.CHOICE
    ).first()
    if definition is None:
        return None
    lookup = f"attributes__{definition.key}"
    rows = (
        queryset.order_by().values(lookup).annotate(total=Count("id")).filter(total__gt=0).order_by("-total")
    )
    allowed = set(definition.choice_list)
    options = [
        {"value": row[lookup], "count": row["total"]}
        for row in rows if row[lookup] in allowed
    ][:limit]
    if not options:
        return None
    return {"definition": definition, "param": f"a_{definition.key}", "options": options}


HOMEPAGE_PLACEMENTS = (Promotion.Placement.HOMEPAGE, Promotion.Placement.BOTH)
CATEGORY_PLACEMENTS = (Promotion.Placement.CATEGORY, Promotion.Placement.BOTH)


def with_promotion(queryset, placements):
    """Annotate ``is_promoted`` for listings with a running promotion in one of ``placements``."""
    return queryset.annotate(is_promoted=Exists(
        Promotion.objects.active().filter(product=OuterRef("pk"), placement__in=placements)
    ))
