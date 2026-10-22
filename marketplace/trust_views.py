"""Views for verification, reviews, blocking, user reports, help pages and account deletion."""
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import throttling, trust
from .forms import AccountDeletionForm, SellerReviewForm, SellerVerificationForm, SupportRequestForm, UserReportForm
from .models import SellerVerification, User, UserBlock, UserReport

SUPPORT_REQUESTS_PER_HOUR = 5
USER_REPORTS_PER_HOUR = 10


def _safe_next(request, fallback="/"):
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


# ---------------------------------------------------------------- seller verification

@login_required
def seller_verification(request):
    if request.user.role != User.Role.SELLER:
        messages.info(request, "Set up a seller account before requesting verification.")
        return redirect("become_seller")
    latest = request.user.verifications.first()
    can_submit = not request.user.is_verified_seller and not (
        latest and latest.status == SellerVerification.Status.PENDING
    )
    form = SellerVerificationForm(request.POST or None, request.FILES or None, initial={
        "legal_name": request.user.get_full_name(),
    })
    if request.method == "POST" and can_submit and form.is_valid():
        verification = form.save(commit=False)
        verification.user = request.user
        verification.save()
        messages.success(request, "Thanks. Our team will review your documents, usually within two working days.")
        return redirect("seller_verification")
    return render(request, "marketplace/seller_verification.html", {
        "form": form, "latest": latest, "can_submit": can_submit,
    })


@staff_member_required
def verification_document(request, pk):
    """Identity documents are only ever served to staff with permission to view verifications."""
    if not request.user.has_perm("marketplace.view_sellerverification"):
        raise Http404()
    verification = get_object_or_404(SellerVerification, pk=pk)
    response = FileResponse(verification.document.open("rb"))
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response


# ---------------------------------------------------------------- reviews

@login_required
@require_POST
def review_order(request, number):
    from commerce.models import Order

    order = get_object_or_404(Order, number=number, buyer=request.user)
    if not trust.can_review(order, request.user):
        messages.error(request, "You can review a seller once, after the order is completed.")
        return redirect("commerce:order_detail", number=number)
    form = SellerReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.order, review.seller, review.buyer = order, order.seller, request.user
        review.save()
        messages.success(request, "Thanks for your review.")
    else:
        messages.error(request, "Choose a rating from 1 to 5 stars.")
    return redirect("commerce:order_detail", number=number)


# ---------------------------------------------------------------- blocking and user reports

@login_required
@require_POST
def toggle_block(request, user_id):
    other = get_object_or_404(User, pk=user_id)
    if other.pk == request.user.pk or other.is_staff:
        raise Http404()
    block = UserBlock.objects.filter(blocker=request.user, blocked=other).first()
    if block:
        block.delete()
        messages.success(request, f"You unblocked {other}.")
    else:
        UserBlock.objects.create(blocker=request.user, blocked=other)
        messages.success(request, f"You blocked {other}. Neither of you can message the other.")
    return redirect(_safe_next(request, "/messages/"))


@login_required
@require_POST
def report_user(request, user_id):
    reported = get_object_or_404(User, pk=user_id)
    destination = _safe_next(request)
    if reported.pk == request.user.pk:
        raise Http404()
    if throttling.hit("user-report", str(request.user.pk), USER_REPORTS_PER_HOUR, 3600):
        messages.error(request, "You have sent several reports recently. Please try again later.")
        return redirect(destination)
    form = UserReportForm(request.POST)
    if form.is_valid():
        if UserReport.objects.filter(reporter=request.user, reported=reported, status=UserReport.Status.OPEN).exists():
            messages.info(request, "You already have an open report about this person.")
        else:
            report = form.save(commit=False)
            report.reporter, report.reported = request.user, reported
            report.save()
            messages.success(request, "Report sent. Our team reviews every report. Reports are private.")
    else:
        messages.error(request, "Choose a reason for your report.")
    return redirect(destination)


# ---------------------------------------------------------------- help centre

HELP_PAGES = {
    "": ("Help centre", "help/index.html"),
    "safety": ("Staying safe", "help/safety.html"),
    "buying": ("How buying works", "help/buying.html"),
    "selling": ("How selling works", "help/selling.html"),
    "prohibited-items": ("Prohibited and restricted items", "help/prohibited.html"),
    "refunds": ("Cancellations, returns and refunds", "help/refunds.html"),
    "fees": ("Fees", "help/fees.html"),
    "privacy": ("Privacy", "help/privacy.html"),
    "terms": ("Terms of use", "help/terms.html"),
}


def help_page(request, slug=""):
    if slug not in HELP_PAGES:
        raise Http404()
    title, template = HELP_PAGES[slug]
    try:
        get_template(template)
    except TemplateDoesNotExist:
        raise Http404()
    return render(request, template, {"page_title": title, "help_pages": HELP_PAGES, "current_help": slug})


def contact_support(request):
    initial = {"email": request.user.email} if request.user.is_authenticated else {}
    if request.GET.get("topic") in dict(SupportRequestForm.base_fields["topic"].choices):
        initial["topic"] = request.GET["topic"]
    form = SupportRequestForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if throttling.hit("support", throttling.client_ip(request), SUPPORT_REQUESTS_PER_HOUR, 3600):
            messages.error(request, "Too many requests from this connection. Please try again in an hour.")
        elif form.is_valid():
            support = form.save(commit=False)
            support.user = request.user if request.user.is_authenticated else None
            support.save()
            messages.success(request, "Message received. Our team will reply by email.")
            return redirect("help")
    return render(request, "help/contact.html", {
        "form": form, "page_title": "Contact support", "help_pages": HELP_PAGES, "current_help": "contact",
    })


# ---------------------------------------------------------------- account deletion

@login_required
def delete_account(request):
    form = AccountDeletionForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            trust.delete_account(request.user)
        except trust.AccountDeletionBlocked as exc:
            messages.error(request, str(exc))
        else:
            logout(request)
            messages.success(request, "Your account was deleted and your personal details removed.")
            return redirect("home")
    return render(request, "registration/delete_account.html", {"form": form})
