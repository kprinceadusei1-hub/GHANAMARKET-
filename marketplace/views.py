from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
from django.db.models import Case, Count, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value, When
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    UserReportForm,
    ListingReportForm,
    MessageForm,
    ProductForm,
    ProfileForm,
    RegistrationForm,
    SellerUpgradeForm,
)
from .models import (
    Category, Conversation, Favorite, GhanaRegion, Message, Product, ProductPhoto, SearchTerm, User,
)
from . import catalog, throttling, trust

LOGIN_FAILURES_PER_ACCOUNT = 5
LOGIN_ATTEMPTS_PER_IP = 30
LOGIN_WINDOW_SECONDS = 15 * 60
MESSAGES_PER_WINDOW = 30
MESSAGE_WINDOW_SECONDS = 10 * 60
REPORTS_PER_HOUR = 10
PASSWORD_RESETS_PER_HOUR = 5
SELLER_PENDING_MESSAGE = (
    "Thanks! Your seller request was sent to our team. You can post ads as soon as it is approved, "
    "usually within one working day. We will notify you."
)


def _seller_cannot_post(request):
    """Redirect response when a seller account is not yet approved to post, otherwise None."""
    if request.user.seller_status == User.SellerStatus.APPROVED:
        return None
    if request.user.seller_status == User.SellerStatus.REJECTED:
        messages.error(request, "Your seller request was not approved. See the note in My shop, then you can apply again.")
    else:
        messages.info(request, "Your seller account is waiting for admin approval. You can post ads once it is approved.")
    return redirect("seller_listings")
REGISTRATIONS_PER_HOUR = 10
NEW_LISTINGS_PER_DAY = 20


class ThrottledLoginView(auth_views.LoginView):
    """Login that slows down password guessing per account and per IP address."""

    template_name = "registration/login.html"

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip().lower()
        ip = throttling.client_ip(request)
        if throttling.hit("login-ip", ip, LOGIN_ATTEMPTS_PER_IP, LOGIN_WINDOW_SECONDS) or (
            username and throttling.is_limited("login-user", username, LOGIN_FAILURES_PER_ACCOUNT)
        ):
            form = self.get_form()
            form.errors.clear()
            return self.render_to_response(self.get_context_data(form=form, throttled=True), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        username = self.request.POST.get("username", "").strip().lower()
        if username:
            throttling.record_attempt("login-user", username, LOGIN_WINDOW_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        throttling.reset("login-user", form.get_user().get_username().lower())
        return super().form_valid(form)


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """Password reset that never reveals whether an email is registered and limits requests per IP."""

    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"

    def post(self, request, *args, **kwargs):
        if throttling.hit("password-reset", throttling.client_ip(request), PASSWORD_RESETS_PER_HOUR, 3600):
            # Same destination as a successful request, so the limit does not leak account data.
            return redirect("password_reset_done")
        return super().post(request, *args, **kwargs)


def _message_limit_reached(request):
    if throttling.hit("message", str(request.user.pk), MESSAGES_PER_WINDOW, MESSAGE_WINDOW_SECONDS):
        messages.error(request, "You are sending messages too quickly. Please wait a few minutes and try again.")
        return True
    return False


_published_products = catalog.published_products
RECENTLY_VIEWED_SESSION_KEY = "recently_viewed"
RECENTLY_VIEWED_LIMIT = 12
LISTINGS_PER_PAGE = 24


def _favorite_ids(request):
    if not request.user.is_authenticated:
        return set()
    return set(Favorite.objects.filter(user=request.user).values_list("product_id", flat=True))


def _remember_viewed(request, product):
    viewed = [pk for pk in request.session.get(RECENTLY_VIEWED_SESSION_KEY, []) if pk != product.pk]
    request.session[RECENTLY_VIEWED_SESSION_KEY] = [product.pk, *viewed][:RECENTLY_VIEWED_LIMIT]


def _recently_viewed(request, exclude=None, limit=6):
    ids = [pk for pk in request.session.get(RECENTLY_VIEWED_SESSION_KEY, []) if pk != exclude][:limit]
    if not ids:
        return []
    found = {p.pk: p for p in catalog.showcase_products().filter(pk__in=ids).annotate(
        extra_photo_count=Count("photos", distinct=True))}
    return [found[pk] for pk in ids if pk in found]


def _gallery_photos(product):
    photos = []
    if product.image:
        photos.append({
            "url": product.image.url,
            "alt": f"{product.title} main photo",
        })
    photos.extend(
        {
            "url": photo.image.url,
            "alt": f"{product.title} photo {index + (2 if product.image else 1)}",
        }
        for index, photo in enumerate(product.photos.all())
    )
    return photos


def home(request):
    published_products = catalog.showcase_products()
    region_labels = dict(GhanaRegion.choices)
    popular_regions = [
        {"name": item["region"], "label": region_labels[item["region"]], "count": item["total"]}
        for item in (
            published_products.exclude(region="").order_by()
            .values("region").annotate(total=Count("id")).order_by("-total", "region")[:6]
        )
    ]
    products = list(published_products.annotate(extra_photo_count=Count("photos", distinct=True))[:12])
    seller_storefronts = list(
        User.objects.filter(role=User.Role.SELLER)
        .annotate(active_listing_count=Count(
            "products",
            filter=Q(products__status=Product.Status.PUBLISHED, products__is_demo=False),
            distinct=True,
        ))
        .filter(active_listing_count__gt=0)
        .order_by("-active_listing_count", "username")[:4]
    )
    collections = []
    for category in catalog.categories_with_counts():
        if not category["count"]:
            continue
        cover = published_products.filter(category_id=category["value"]).exclude(image="").first()
        if cover:
            collections.append({**category, "cover": cover})
        if len(collections) == 6:
            break
    with_photo_counts = published_products.annotate(extra_photo_count=Count("photos", distinct=True))
    tabs = []
    if products:
        featured = list(catalog.with_promotion(with_photo_counts.exclude(image=""), catalog.HOMEPAGE_PLACEMENTS).annotate(
            verified=Case(When(seller__verified_at__isnull=False, then=Value(1)), default=Value(0),
                          output_field=IntegerField()),
        ).order_by("is_demo", "-is_promoted", "-verified", "-created_at")[:8])
        trending = list(with_photo_counts.annotate(
            saves=Count("favorites", distinct=True), chats=Count("conversations", distinct=True),
        ).filter(Q(saves__gt=0) | Q(chats__gt=0)).order_by("-saves", "-chats", "-created_at")[:8])
        viewed_categories = list(Product.objects.filter(
            pk__in=request.session.get(RECENTLY_VIEWED_SESSION_KEY, [])
        ).values_list("category_id", flat=True).distinct())
        recommended = list(with_photo_counts.filter(category_id__in=viewed_categories).exclude(
            pk__in=request.session.get(RECENTLY_VIEWED_SESSION_KEY, [])
        )[:8]) if viewed_categories else []
        tabs = [tab for tab in (
            ("featured", "Featured", featured),
            ("trending", "Trending", trending),
            ("new", "New Arrivals", products[:8]),
            ("recommended", "Recommended", recommended),
        ) if tab[2]]
    nearby = []
    area = buyer_area(request)
    if area:
        nearby = list(with_proximity(with_photo_counts.filter(region=area["region"]), area).order_by(
            "is_demo", "proximity", "-created_at")[:4])
    verified_sellers = [seller for seller in seller_storefronts if seller.verified_at]
    own_pending = []
    if request.user.is_authenticated and request.user.role == User.Role.SELLER:
        own_pending = list(Product.objects.filter(
            seller=request.user, status__in=(Product.Status.PENDING, Product.Status.REJECTED)
        ).order_by("-updated_at")[:3])
    return render(request, "home.html", {
        "own_pending": own_pending,
        "product_tabs": tabs,
        "nearby": nearby,
        "area": area,
        "verified_sellers": verified_sellers,
        "collections": collections,
        "products": products,
        "hero_products": [product for product in products if product.image][:3],
        "seller_storefronts": seller_storefronts,
        "listing_count": published_products.count(),
        "categories": catalog.categories_with_counts(),
        "regions": GhanaRegion.choices,
        "popular_regions": popular_regions,
        "popular_searches": SearchTerm.objects.filter(is_hidden=False)[:8],
        "recently_viewed": _recently_viewed(request),
        "has_demo_listings": published_products.filter(is_demo=True).exists(),
        "favorite_ids": _favorite_ids(request),
        "favorite_return": "home",
    })


def category_index(request):
    counts = {item["value"]: item["count"] for item in catalog.categories_with_counts()}
    categories = catalog.top_categories().prefetch_related(
        Prefetch("children", queryset=Category.objects.filter(is_active=True))
    )
    return render(request, "marketplace/category_index.html", {
        "category_tree": [(category, counts.get(category.slug, 0)) for category in categories],
    })


def search_suggestions(request):
    """Lightweight JSON suggestions for the header search box."""
    query = " ".join(request.GET.get("q", "").split())[:60]
    if len(query) < 2:
        return JsonResponse({"categories": [], "listings": []})
    list_url = reverse("product_list")
    categories = []
    for category in Category.objects.filter(is_active=True, name__icontains=query).select_related("parent")[:4]:
        url = f"{list_url}?category={category.top_level.slug}"
        if category.parent_id:
            url += f"&sub={category.slug}"
        categories.append({"label": str(category), "url": url})
    titles = (
        catalog.apply_search(catalog.showcase_products(), query)
        .order_by("-relevance", "-created_at").values_list("title", flat=True)[:12]
    )
    seen, listings = set(), []
    for title in titles:
        if title.lower() not in seen:
            seen.add(title.lower())
            listings.append(title)
        if len(listings) == 6:
            break
    return JsonResponse({"categories": categories, "listings": listings})


def seller_storefront(request, pk):
    seller = get_object_or_404(
        User.objects.filter(role=User.Role.SELLER), pk=pk
    )
    products = _published_products().filter(seller=seller).annotate(
        extra_photo_count=Count("photos", distinct=True)
    )
    return render(request, "marketplace/seller_storefront.html", {
        "seller_profile": seller,
        "seller_rating": trust.seller_rating(seller),
        "reviews": seller.reviews_received.filter(is_hidden=False).select_related("buyer")[:10],
        "report_user_form": UserReportForm(),
        "products": products,
        "listing_count": products.count(),
        "favorite_ids": _favorite_ids(request),
        "favorite_return": "list",
    })


def health(request):
    return JsonResponse({"status": "ok", "service": "africa-marketplace"})


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    data = request.POST if request.method == "POST" else None
    initial = {"role": User.Role.SELLER} if request.GET.get("role") == "seller" else {}
    form = RegistrationForm(data, initial=initial)
    if request.method == "POST" and throttling.hit(
        "register", throttling.client_ip(request), REGISTRATIONS_PER_HOUR, 3600
    ):
        messages.error(request, "Too many sign-ups from this connection. Please try again later.")
        return render(request, "registration/register.html", {"form": form}, status=429)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.country = (user.country or settings.DEFAULT_COUNTRY).upper()
        if user.role == User.Role.SELLER:
            user.request_seller_approval()
        user.save()
        login(request, user)
        messages.success(request, "Your account is ready.")
        if user.role == User.Role.SELLER:
            messages.info(request, SELLER_PENDING_MESSAGE)
            return redirect("seller_listings")
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


@login_required
def account_settings(request):
    form = ProfileForm(
        request.POST if request.method == "POST" else None,
        instance=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your account details have been updated.")
        return redirect("account_settings")
    return render(request, "registration/account_settings.html", {"form": form})


@login_required
def become_seller(request):
    if request.user.role == User.Role.SELLER and request.user.seller_status != User.SellerStatus.REJECTED:
        return redirect("seller_listings")
    form = SellerUpgradeForm(
        request.POST if request.method == "POST" else None,
        instance=request.user,
    )
    if request.method == "POST" and form.is_valid():
        seller = form.save(commit=False)
        seller.request_seller_approval()
        seller.save()
        messages.success(request, SELLER_PENDING_MESSAGE)
        return redirect("seller_listings")
    return render(request, "registration/seller_upgrade.html", {"form": form})


AREA_SESSION_KEY = "buyer_area"


def buyer_area(request):
    """The buyer's area as {"town", "region"}: chosen on the site, else from their profile. Empty if unknown."""
    chosen = request.session.get(AREA_SESSION_KEY)
    if chosen and chosen.get("region"):
        return chosen
    user = request.user
    if user.is_authenticated and user.region:
        from .ghana_places import REGION_NAMES

        town = (user.city or "").strip()
        return {"town": "" if town.lower() in REGION_NAMES else town, "region": user.region}
    return {}


def with_proximity(products, area):
    """Annotate ``proximity``: 0 = same town, 1 = same region, 2 = elsewhere in Ghana."""
    whens = []
    if area.get("town"):
        whens.append(When(region=area["region"], city__iexact=area["town"], then=Value(0)))
    whens.append(When(region=area["region"], then=Value(1)))
    return products.annotate(proximity=Case(*whens, default=Value(2), output_field=IntegerField()))


@require_POST
def set_area(request):
    """Remember where the buyer is shopping from (this browser only), or forget it."""
    from django.core.exceptions import ValidationError

    from .ghana_places import clean_city

    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = reverse("product_list")
    if request.POST.get("clear"):
        request.session.pop(AREA_SESSION_KEY, None)
        return redirect(next_url)
    region = request.POST.get("region", "").strip()
    if region not in {value for value, _ in GhanaRegion.choices}:
        messages.error(request, "Choose your region to see listings near you.")
        return redirect(next_url)
    try:
        town = clean_city(request.POST.get("town", "")[:100])
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect(next_url)
    request.session[AREA_SESSION_KEY] = {"town": town, "region": region}
    messages.success(request, f"Showing listings near {', '.join(part for part in (town, region) if part)} first.")
    return redirect(next_url)


def product_list(request):
    products = catalog.showcase_products().annotate(extra_photo_count=Count("photos", distinct=True))
    params = request.GET
    query = " ".join(params.get("q", "").split())[:100]
    region = params.get("region", "").strip()
    city = params.get("city", "").strip()[:100]
    minimum_price = params.get("min_price", "").strip()
    maximum_price = params.get("max_price", "").strip()
    condition = params.get("condition", "").strip()
    sort = params.get("sort", "").strip()
    area = buyer_area(request)
    near_me = params.get("near") == "1" and bool(area)

    category = catalog.top_categories().filter(slug=params.get("category", "").strip()).first()
    subcategory = None
    if category:
        products = products.filter(category=category)
        subcategory = category.children.filter(is_active=True, slug=params.get("sub", "").strip()).first()
        if subcategory:
            products = products.filter(subcategory=subcategory)
    if query:
        products = catalog.apply_search(products, query)
    if region in {value for value, _ in GhanaRegion.choices}:
        products = products.filter(region=region)
    else:
        region = ""
    if near_me:
        products = products.filter(region=area["region"])
    if city:
        products = products.filter(city__icontains=city)
    quick_prices = catalog.price_buckets(products)
    for raw, lookup in ((minimum_price, "price__gte"), (maximum_price, "price__lte")):
        amount = catalog.parse_decimal(raw) if raw else None
        if amount is not None:
            products = products.filter(**{lookup: amount})
    if condition in {value for value, _ in Product.Condition.choices}:
        products = products.filter(condition=condition)
    else:
        condition = ""
    verified_only = params.get("verified") == "1"
    if verified_only:
        products = products.filter(seller__verified_at__isnull=False)
    checkout_only = params.get("checkout") == "1"
    if checkout_only:
        products = products.filter(allows_checkout=True, category__allows_checkout=True, stock_quantity__gt=0)
    attribute_widgets, attribute_q, active_attributes = catalog.attribute_filters(subcategory or category, params)
    facet = catalog.choice_facet(products, subcategory or category)
    if facet:
        for option in facet["options"]:
            chosen = params.copy()
            chosen.pop("page", None)
            option["selected"] = params.get(facet["param"]) == option["value"]
            if option["selected"]:
                chosen.pop(facet["param"], None)
            else:
                chosen[facet["param"]] = option["value"]
            option["url"] = "?" + chosen.urlencode()
    products = products.filter(attribute_q)
    attribute_chips = []
    for label, value, param_names in active_attributes:
        remaining = params.copy()
        for name in (*param_names, "page"):
            remaining.pop(name, None)
        attribute_chips.append({"label": label, "value": value, "remove_url": "?" + remaining.urlencode()})

    sort_options = [("newest", "Most recent"), ("price-low", "Price: low to high"), ("price-high", "Price: high to low")]
    if query:
        sort_options.insert(0, ("relevance", "Best match"))
    if area:
        sort_options.append(("nearest", "Closest to me"))
    orderings = {
        "relevance": ("-relevance", "-created_at"),
        "newest": ("-created_at",),
        "price-low": ("price", "-created_at"),
        "price-high": ("-price", "-created_at"),
        "nearest": ("proximity", "-created_at"),
    }
    default_sort = "nearest" if near_me else ("relevance" if query else "newest")
    if sort not in dict(sort_options):
        sort = default_sort
    if area:
        products = with_proximity(products, area)
    products = catalog.with_promotion(products, catalog.CATEGORY_PLACEMENTS)
    ordering = orderings[sort]
    if sort in {"newest", "relevance"} and (category or query):
        ordering = ("-is_promoted", *ordering)
    if sort != "price-low" and sort != "price-high":
        ordering = ("is_demo", *ordering)  # real ads before previews
    products = products.order_by(*ordering)

    result_count = products.count()
    if query and result_count and "page" not in params:
        SearchTerm.record(query)
    page = Paginator(products, LISTINGS_PER_PAGE).get_page(params.get("page"))
    return render(request, "marketplace/product_list.html", {
        "page": page,
        "products": page.object_list,
        "query": query,
        "selected_category": category.slug if category else "",
        "selected_category_label": category.name if category else "",
        "category": category,
        "subcategory": subcategory,
        "subcategories": category.children.filter(is_active=True) if category else [],
        "attribute_widgets": attribute_widgets,
        "attribute_chips": attribute_chips,
        "quick_prices": quick_prices,
        "facet": facet,
        "has_extra_filters": bool(
            region or city or minimum_price or maximum_price or condition or active_attributes or verified_only
            or checkout_only or near_me
        ),
        "area": area,
        "near_me": near_me,
        "area_label": ", ".join(part for part in (area.get("town"), area.get("region")) if part),
        "verified_only": verified_only,
        "checkout_only": checkout_only,
        "selected_region": region,
        "selected_city": city,
        "minimum_price": minimum_price,
        "maximum_price": maximum_price,
        "selected_condition": condition,
        "selected_sort": sort,
        "default_sort": default_sort,
        "sort_options": sort_options,
        "condition_options": Product.Condition.choices,
        "categories": [(c.slug, c.name) for c in catalog.top_categories()],
        "regions": GhanaRegion.choices,
        "result_count": result_count,
        "has_demo_listings": products.filter(is_demo=True).exists(),
        "favorite_ids": _favorite_ids(request),
        "favorite_return": "list",
    })


@login_required
def saved_listings(request):
    products = _published_products().filter(favorites__user=request.user).annotate(
        extra_photo_count=Count("photos", distinct=True)
    )
    return render(request, "marketplace/saved_listings.html", {
        "products": products,
        "favorite_ids": set(products.values_list("pk", flat=True)),
        "favorite_return": "saved",
    })


@login_required
@require_POST
def toggle_favorite(request, product_id):
    product = get_object_or_404(
        Product.objects.filter(status=Product.Status.PUBLISHED, is_demo=False), pk=product_id
    )
    favorite, created = Favorite.objects.get_or_create(user=request.user, product=product)
    if not created:
        favorite.delete()
    destination = request.POST.get("next", "")
    if destination in {"saved", "list", "home"}:
        return redirect({"saved": "saved_listings", "list": "product_list", "home": "home"}[destination])
    return redirect("product_detail", pk=product.pk)


def _detail_context(request, product, **overrides):
    """Shared context for the listing page, including re-renders after form errors."""
    user = request.user
    favorite_ids = _favorite_ids(request)
    similar = catalog.showcase_products().filter(category_id=product.category_id).exclude(pk=product.pk)
    if product.subcategory_id:
        # Same subcategory first, then the rest of the category.
        similar = similar.annotate(same_sub=Case(
            When(subcategory_id=product.subcategory_id, then=Value(1)), default=Value(0), output_field=IntegerField(),
        )).order_by("-same_sub", "-created_at")
    context = {
        "product": product,
        "gallery_photos": _gallery_photos(product),
        "message_form": MessageForm(),
        "report_form": ListingReportForm(),
        "is_favorite": product.pk in favorite_ids,
        "favorite_ids": favorite_ids,
        "can_chat": (
            product.allows_direct_contact
            and not (user.is_authenticated and User.blocked_between(user, product.seller))
            and user.is_authenticated
            and user.role == User.Role.BUYER
            and user.pk != product.seller_id
            and product.status == Product.Status.PUBLISHED
            and not product.is_demo
        ),
        "seller_active_count": _published_products().filter(seller=product.seller).count(),
        "seller_rating": trust.seller_rating(product.seller),
        "similar_products": list(similar.annotate(extra_photo_count=Count("photos", distinct=True))[:8]),
        "attribute_items": product.attribute_items(),
        "can_buy": product.can_checkout and user.pk != product.seller_id,
        "stock_choices": range(1, min(product.stock_quantity, 10) + 1),
        "recently_viewed": _recently_viewed(request, exclude=product.pk),
    }
    from urllib.parse import quote

    listing_url = request.build_absolute_uri(reverse("product_detail", args=[product.pk]))
    is_live = product.status == Product.Status.PUBLISHED and not product.is_demo
    if is_live:
        context["whatsapp_share_url"] = "https://wa.me/?text=" + quote(
            f"{product.title} – GH₵ {product.price:,.2f} on GhanaMarket: {listing_url}"
        )
    seller = product.seller
    if is_live and seller.whatsapp_contact and seller.whatsapp_number and user.pk != seller.pk and not (
        user.is_authenticated and User.blocked_between(user, seller)
    ):
        # Signed-in buyers only, so phone numbers are not handed to scrapers.
        context["whatsapp_contact_url"] = (
            f"https://wa.me/{seller.whatsapp_number}?text=" + quote(
                f"Hello, I saw your ad “{product.title}” on GhanaMarket: {listing_url} Is it still available?"
            ) if user.is_authenticated else f"{reverse('login')}?next={reverse('product_detail', args=[product.pk])}"
        )
    context.update(overrides)
    return context


def product_detail(request, pk):
    products = catalog.showcase_products()
    if request.user.is_authenticated:
        products = products | Product.objects.filter(seller=request.user)
    product = get_object_or_404(products.prefetch_related("photos"), pk=pk)
    context = _detail_context(request, product)
    if product.status == Product.Status.PUBLISHED:
        _remember_viewed(request, product)
    return render(request, "marketplace/product_detail.html", context)


@login_required
@require_POST
def report_listing(request, product_id):
    product = get_object_or_404(
        Product.objects.filter(
            status=Product.Status.PUBLISHED, is_demo=False
        ).select_related("seller"),
        pk=product_id,
    )
    if product.seller_id == request.user.id:
        messages.error(request, "You cannot report your own listing.")
        return redirect("product_detail", pk=product.pk)
    if throttling.hit("report", str(request.user.pk), REPORTS_PER_HOUR, 3600):
        messages.error(request, "You have sent several reports recently. Please try again later.")
        return redirect("product_detail", pk=product.pk)
    form = ListingReportForm(request.POST)
    if not form.is_valid():
        return render(
            request, "marketplace/product_detail.html",
            _detail_context(request, product, report_form=form),
        )
    report, created = product.reports.get_or_create(
        reporter=request.user,
        defaults={
            "reason": form.cleaned_data["reason"],
            "details": form.cleaned_data["details"],
        },
    )
    if created:
        messages.success(request, "Thank you. Your report has been sent to the admin team.")
    else:
        messages.info(request, "You have already reported this listing.")
    return redirect("product_detail", pk=product.pk)


@login_required
def seller_listings(request):
    if request.user.role != User.Role.SELLER:
        messages.error(request, "Seller accounts can manage their own listings.")
        return redirect("home")
    seller_products = Product.objects.filter(seller=request.user)
    counts = seller_products.aggregate(
        total=Count("id"),
        live=Count("id", filter=Q(status=Product.Status.PUBLISHED)),
        pending=Count("id", filter=Q(status=Product.Status.PENDING)),
        needs_changes=Count("id", filter=Q(status=Product.Status.REJECTED)),
        sold=Count("id", filter=Q(status=Product.Status.SOLD)),
    )
    products = seller_products.annotate(
        extra_photo_count=Count("photos", distinct=True)
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        products = products.filter(
            Q(title__icontains=query)
            | Q(brand__icontains=query)
            | Q(model__icontains=query)
            | Q(city__icontains=query)
        )
    valid_statuses = {value for value, _ in Product.Status.choices}
    if status in valid_statuses:
        products = products.filter(status=status)
    products = products.order_by("-updated_at")
    return render(request, "marketplace/seller_listings.html", {
        "products": products,
        "counts": counts,
        "query": query,
        "selected_status": status,
        "status_options": Product.Status.choices,
        "orders_to_fulfil": request.user.seller_orders.filter(status__in=("paid", "processing")).count(),
    })


def _chosen_category(request):
    """(category, subcategory) picked via ?category=&sub= on the listing form, or None."""
    category = catalog.top_categories().filter(slug=request.GET.get("category", "")).first()
    if category is None:
        return None
    subcategory = category.children.filter(is_active=True, slug=request.GET.get("sub", "")).first()
    return category, subcategory


@login_required
def product_create(request):
    if request.user.role != User.Role.SELLER:
        messages.error(request, "Create a seller account to publish product listings.")
        return redirect("home")
    blocked = _seller_cannot_post(request)
    if blocked:
        return blocked
    chosen = _chosen_category(request)
    if request.method != "POST" and chosen is None:
        return render(request, "marketplace/category_picker.html", {
            "category_tree": catalog.top_categories().prefetch_related(
                Prefetch("children", queryset=Category.objects.filter(is_active=True))
            ),
        })
    data = request.POST if request.method == "POST" else None
    files = request.FILES if request.method == "POST" else None
    category, subcategory = chosen or (None, None)
    form = ProductForm(data, files, category=category, initial={"category": category, "subcategory": subcategory})
    if request.method == "POST" and throttling.is_limited(
        "new-listing", str(request.user.pk), NEW_LISTINGS_PER_DAY
    ):
        messages.error(request, f"You can post up to {NEW_LISTINGS_PER_DAY} listings a day. Please try again tomorrow.")
        return redirect("seller_listings")
    if request.method == "POST" and form.is_valid():
        throttling.record_attempt("new-listing", str(request.user.pk), 24 * 3600)
        product = form.save(commit=False)
        product.seller = request.user
        product.currency = settings.DEFAULT_CURRENCY
        product.country = (request.user.country or settings.DEFAULT_COUNTRY).upper()
        product.status = Product.Status.PENDING
        product.risk_flags = trust.listing_risk_flags(product)
        uploaded_images = form.cleaned_data["images"]
        if uploaded_images:
            product.image = uploaded_images.pop(0)
        product.save()
        ProductPhoto.objects.bulk_create([
            ProductPhoto(product=product, image=image, position=index)
            for index, image in enumerate(uploaded_images, start=1)
        ])
        messages.success(
            request,
            "Your listing was submitted for admin review. It will appear publicly after approval.",
        )
        return redirect("product_detail", pk=product.pk)
    return render(request, "marketplace/product_form.html", {
        "form": form,
        "heading": "Create a listing",
    })


@login_required
def product_update(request, pk):
    if request.user.role != User.Role.SELLER:
        messages.error(request, "Only seller accounts can manage listings.")
        return redirect("home")
    blocked = _seller_cannot_post(request)
    if blocked:
        return blocked
    product = get_object_or_404(Product, pk=pk, seller=request.user)
    data = request.POST if request.method == "POST" else None
    files = request.FILES if request.method == "POST" else None
    chosen = _chosen_category(request)
    initial = {"category": chosen[0], "subcategory": chosen[1]} if chosen else None
    form = ProductForm(data, files, instance=product, category=chosen[0] if chosen else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.status = Product.Status.PENDING
        product.moderation_note = ""
        product.risk_flags = trust.listing_risk_flags(product)
        uploaded_images = form.cleaned_data["images"]
        start_position = product.photos.count() + (1 if product.image else 0)
        if uploaded_images and not product.image:
            product.image = uploaded_images.pop(0)
        product.save()
        ProductPhoto.objects.bulk_create([
            ProductPhoto(product=product, image=image, position=start_position + index)
            for index, image in enumerate(uploaded_images)
        ])
        messages.success(
            request,
            "Your changes were submitted for admin review. The listing is hidden until approval.",
        )
        return redirect("product_detail", pk=product.pk)
    return render(request, "marketplace/product_form.html", {
        "form": form,
        "heading": "Edit listing",
        "product": product,
    })


@login_required
@require_POST
def seller_listing_status(request, pk):
    if request.user.role != User.Role.SELLER:
        messages.error(request, "Only seller accounts can manage listings.")
        return redirect("home")

    product = get_object_or_404(Product, pk=pk, seller=request.user)
    action = request.POST.get("action")
    if action == "deactivate" and product.status in {
        Product.Status.PUBLISHED,
        Product.Status.PENDING,
        Product.Status.REJECTED,
    }:
        product.status = Product.Status.DRAFT
        product.moderation_note = ""
        product.save(update_fields=("status", "moderation_note", "updated_at"))
        messages.success(request, "Listing deactivated. It is hidden from buyers and can be submitted again later.")
    elif action == "delete":
        if product.conversations.exists() or product.reports.exists():
            messages.error(
                request,
                "This listing has buyer conversations or reports linked to it, so it cannot be deleted. "
                "Deactivate it instead to hide it from buyers.",
            )
        else:
            title = product.title
            image_files = [photo.image for photo in product.photos.all()]
            if product.image:
                image_files.append(product.image)
            product.delete()
            for image in image_files:
                image.delete(save=False)
            messages.success(request, f"“{title}” was permanently deleted.")
    elif action == "reactivate" and product.status == Product.Status.DRAFT:
        product.status = Product.Status.PENDING
        product.moderation_note = ""
        product.save(update_fields=("status", "moderation_note", "updated_at"))
        messages.success(request, "Listing resubmitted for admin review. It remains hidden until approved.")
    else:
        messages.error(request, "That listing action is not available for its current status.")
    return redirect("seller_listings")


@login_required
def conversation_list(request):
    latest_message = Message.objects.filter(
        conversation=OuterRef("pk")
    ).order_by("-created_at")
    conversations = (
        Conversation.objects.filter(Q(buyer=request.user) | Q(seller=request.user))
        .select_related("product", "buyer", "seller")
        .annotate(
            latest_message_body=Subquery(latest_message.values("body")[:1]),
            latest_message_at=Subquery(latest_message.values("created_at")[:1]),
            unread=Count("messages", filter=~Q(messages__sender=request.user) & (
                (Q(buyer=request.user) & (Q(buyer_last_read_at__isnull=True)
                                          | Q(messages__created_at__gt=F("buyer_last_read_at"))))
                | (Q(seller=request.user) & (Q(seller_last_read_at__isnull=True)
                                             | Q(messages__created_at__gt=F("seller_last_read_at"))))
            )),
        )
    )
    return render(request, "marketplace/conversation_list.html", {
        "conversations": conversations,
    })


@login_required
def conversation_start(request, product_id):
    if request.method != "POST":
        return redirect("product_detail", pk=product_id)
    product = get_object_or_404(
        Product.objects.filter(status=Product.Status.PUBLISHED, is_demo=False).select_related("seller"),
        pk=product_id,
    )
    if request.user.role != User.Role.BUYER:
        messages.error(request, "Only buyer accounts can start a conversation.")
        return redirect("product_detail", pk=product.pk)
    if product.seller_id == request.user.id:
        messages.error(request, "You cannot message yourself about your listing.")
        return redirect("product_detail", pk=product.pk)
    if product.is_demo:
        messages.info(request, "Demo listings are for preview only and cannot receive messages.")
        return redirect("product_detail", pk=product.pk)
    if not product.allows_direct_contact:
        messages.info(request, "This seller sells this item through online checkout only.")
        return redirect("product_detail", pk=product.pk)
    if User.blocked_between(request.user, product.seller):
        messages.error(request, "You cannot message this seller.")
        return redirect("product_detail", pk=product.pk)
    if _message_limit_reached(request):
        return redirect("product_detail", pk=product.pk)
    form = MessageForm(request.POST)
    if form.is_valid():
        conversation, _ = Conversation.objects.get_or_create(
            product=product,
            buyer=request.user,
            defaults={"seller": product.seller},
        )
        if conversation.seller_id != product.seller_id:
            messages.error(request, "This conversation is no longer available.")
            return redirect("product_detail", pk=product.pk)
        message = form.save(commit=False)
        message.conversation = conversation
        message.sender = request.user
        message.save()
        conversation.save(update_fields=("updated_at",))
        return redirect("conversation_detail", pk=conversation.pk)
    return render(
        request, "marketplace/product_detail.html",
        _detail_context(request, product, message_form=form),
    )


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related("product", "buyer", "seller"),
        Q(buyer=request.user) | Q(seller=request.user),
        pk=pk,
    )
    other = conversation.seller if request.user.pk == conversation.buyer_id else conversation.buyer
    is_blocked = User.blocked_between(request.user, other)
    if request.method == "POST" and is_blocked:
        messages.error(request, "Messages are turned off because one of you blocked the other.")
        return redirect("conversation_detail", pk=conversation.pk)
    if request.method == "POST" and _message_limit_reached(request):
        return redirect("conversation_detail", pk=conversation.pk)
    form = MessageForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        message.conversation = conversation
        message.sender = request.user
        message.save()
        conversation.save(update_fields=("updated_at",))
        return redirect("conversation_detail", pk=conversation.pk)
    conversation.mark_read(request.user)
    return render(request, "marketplace/conversation_detail.html", {
        "conversation": conversation,
        "thread_messages": conversation.messages.select_related("sender"),
        "form": form,
        "other_user": other,
        "is_blocked": is_blocked,
        "i_blocked": request.user.has_blocked(other),
        "report_user_form": UserReportForm(),
    })


@login_required
def notification_list(request):
    if request.method == "POST":
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return redirect("notification_list")
    return render(request, "marketplace/notification_list.html", {
        "notifications": request.user.notifications.all()[:100],
    })


@login_required
def notification_open(request, pk):
    notification = get_object_or_404(request.user.notifications, pk=pk)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=("is_read",))
    # Stored links are site paths; refuse anything that could leave the site.
    url = notification.url
    if not url.startswith("/") or not url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        url = reverse("notification_list")
    return redirect(url)
