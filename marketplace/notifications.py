"""In-app notifications with an optional email copy.

Email goes through Django's configured backend (console in development, SMTP in production).
SMS is not wired up: no SMS provider is configured. Add one here when credentials exist.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify(user, title, body="", url="", email=True):
    from .models import Notification

    notification = Notification.objects.create(user=user, title=title[:120], body=body[:300], url=url[:200])
    if email and settings.NOTIFICATION_EMAILS_ENABLED and user.email:
        link = f"\n\n{settings.SITE_URL.rstrip('/')}{url}" if url and settings.SITE_URL else ""
        try:
            send_mail(f"GhanaMarket: {title}", f"{body}{link}", None, [user.email], fail_silently=False)
        except Exception:  # Email problems must never break an order or payment.
            logger.exception("Could not send notification email to user %s", user.pk)
    return notification
