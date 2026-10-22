"""Paystack integration (https://paystack.com/docs/api/).

Uses only the standard library. Secret keys come from the environment and are never logged or
stored. Card data never touches this application: buyers pay on Paystack's hosted page.
"""
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from .base import (
    PaymentError, PaymentProvider, VerificationResult, WebhookEvent, WebhookSignatureError, from_subunits, to_subunits,
)

logger = logging.getLogger(__name__)
API_BASE = "https://api.paystack.co"
TIMEOUT_SECONDS = 15
# Only these fields of Paystack's transaction object are kept for reconciliation.
KEPT_FIELDS = ("id", "status", "reference", "amount", "currency", "channel", "gateway_response", "paid_at", "fees")


class PaystackProvider(PaymentProvider):
    name = "paystack"
    label = "Paystack (Mobile Money or card)"

    def __init__(self, secret_key, opener=None):
        self._secret_key = secret_key
        self._open = opener or urllib.request.urlopen

    @property
    def is_test(self):
        return self._secret_key.startswith("sk_test_")

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            API_BASE + path, data=data, method=method,
            headers={
                "Authorization": f"Bearer {self._secret_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._open(request, timeout=TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode("utf-8")).get("message", "")
            except (ValueError, AttributeError):
                message = ""
            logger.warning("Paystack %s %s failed with HTTP %s: %s", method, path, exc.code, message)
            raise PaymentError(message or f"Paystack returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("Paystack %s %s could not be completed: %s", method, path, exc)
            raise PaymentError("The payment provider could not be reached. Please try again.") from exc
        if not payload.get("status"):
            raise PaymentError(payload.get("message", "The payment provider rejected the request."))
        return payload.get("data") or {}

    def initialize(self, payment, email, callback_url):
        data = self._request("POST", "/transaction/initialize", {
            "email": email,
            "amount": str(to_subunits(payment.amount)),
            "currency": payment.currency,
            "reference": payment.reference,
            "callback_url": callback_url,
            "channels": ["mobile_money", "card"],
            "metadata": {"checkout": payment.checkout.reference},
        })
        url = data.get("authorization_url", "")
        if not url.startswith("https://"):
            raise PaymentError("The payment provider did not return a payment page.")
        return url

    def verify(self, payment):
        data = self._request("GET", f"/transaction/verify/{payment.reference}")
        raw = {key: data.get(key) for key in KEPT_FIELDS if key in data}
        status = data.get("status", "")
        if status == "success":
            result_status = "success"
        elif status in {"failed", "reversed", "abandoned"}:
            result_status = "failed"
        else:
            result_status = "pending"
        return VerificationResult(
            status=result_status,
            amount=from_subunits(data.get("amount", 0)),
            currency=data.get("currency", ""),
            channel=data.get("channel", "") or "",
            transaction_id=str(data.get("id", "")),
            message=data.get("gateway_response", "") or "",
            raw=raw,
        )

    def parse_webhook(self, request):
        signature = request.headers.get("X-Paystack-Signature", "")
        body = request.body
        expected = hmac.new(self._secret_key.encode("utf-8"), body, hashlib.sha512).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise WebhookSignatureError("Invalid Paystack signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise WebhookSignatureError("Malformed webhook body") from exc
        data = payload.get("data") or {}
        return WebhookEvent(
            event_key=hashlib.sha256(body).hexdigest(),
            event_type=payload.get("event", ""),
            reference=str(data.get("reference", "")),
            payload={"event": payload.get("event", ""), "data": {k: data.get(k) for k in KEPT_FIELDS if k in data}},
        )

    def refund(self, payment, amount):
        data = self._request("POST", "/refund", {
            "transaction": payment.reference,
            "amount": str(to_subunits(amount)),
        })
        status = "completed" if data.get("status") == "processed" else "requested"
        return status, str(data.get("id", ""))
