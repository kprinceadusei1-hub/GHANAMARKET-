"""Payment provider registry.

``PAYMENT_PROVIDER`` selects the active provider:
  * ``paystack`` – live or test Paystack keys (Mobile Money and cards, Ghana).
  * ``test``     – local simulator, only allowed while DEBUG is on. No money moves.
  * empty        – online payment disabled; checkout explains this honestly.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import PaymentError, PaymentProvider, VerificationResult, WebhookEvent, WebhookSignatureError


def get_provider(name=None):
    name = (name if name is not None else settings.PAYMENT_PROVIDER).strip().lower()
    if not name:
        return None
    if name == "paystack":
        from .paystack import PaystackProvider

        if not settings.PAYSTACK_SECRET_KEY:
            raise ImproperlyConfigured("Set PAYSTACK_SECRET_KEY to use the Paystack payment provider.")
        return PaystackProvider(settings.PAYSTACK_SECRET_KEY)
    if name == "test":
        from .test_provider import TestProvider

        if not settings.DEBUG:
            raise ImproperlyConfigured("The test payment provider cannot be used when DEBUG is off.")
        return TestProvider()
    raise ImproperlyConfigured(f"Unknown PAYMENT_PROVIDER: {name}")


__all__ = [
    "PaymentError", "PaymentProvider", "VerificationResult", "WebhookEvent", "WebhookSignatureError", "get_provider",
]
