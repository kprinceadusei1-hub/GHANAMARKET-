"""Local payment simulator for development (DEBUG only).

The buyer is sent to a clearly labelled in-app page where they choose "succeed" or "fail".
That choice is stored on the Payment and read back by ``verify`` exactly like a real provider's
API would be, so the same server-side verification path is exercised. No money moves.
"""
from django.urls import reverse

from .base import PaymentProvider, VerificationResult, WebhookSignatureError

OUTCOME_KEY = "test_outcome"


class TestProvider(PaymentProvider):
    name = "test"
    label = "Test payments (no real money)"
    is_test = True

    def initialize(self, payment, email, callback_url):
        payment.provider_response = {"callback_url": callback_url}
        payment.save(update_fields=("provider_response",))
        return reverse("commerce:test_payment", args=[payment.reference])

    def verify(self, payment):
        outcome = (payment.provider_response or {}).get(OUTCOME_KEY)
        if outcome == "success":
            return VerificationResult(
                status="success", amount=payment.amount, currency=payment.currency, channel="test",
                transaction_id=f"TEST-{payment.pk}", message="Simulated success", raw={"status": "success"},
            )
        if outcome == "failed":
            return VerificationResult(status="failed", message="Simulated failure", raw={"status": "failed"})
        return VerificationResult(status="pending", raw={"status": "pending"})

    def parse_webhook(self, request):
        raise WebhookSignatureError("The test provider does not send webhooks.")

    def refund(self, payment, amount):
        return "completed", f"TEST-REFUND-{payment.pk}"
