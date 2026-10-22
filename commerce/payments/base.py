from dataclasses import dataclass, field
from decimal import Decimal


class PaymentError(Exception):
    """The provider could not be reached or rejected the request."""


class WebhookSignatureError(Exception):
    """A webhook failed signature validation and must be ignored."""


@dataclass
class VerificationResult:
    status: str  # "success", "failed" or "pending"
    amount: Decimal = Decimal("0")
    currency: str = ""
    channel: str = ""
    transaction_id: str = ""
    message: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class WebhookEvent:
    event_key: str
    event_type: str
    reference: str
    payload: dict


class PaymentProvider:
    name = ""
    label = ""
    is_test = False

    def initialize(self, payment, email, callback_url):
        """Start a payment and return the URL the buyer should be sent to."""
        raise NotImplementedError

    def verify(self, payment):
        """Ask the provider for the authoritative status of ``payment``. Returns VerificationResult."""
        raise NotImplementedError

    def parse_webhook(self, request):
        """Validate and parse a webhook request. Raises WebhookSignatureError when invalid."""
        raise NotImplementedError

    def refund(self, payment, amount):
        """Request a refund. Returns (status, provider_reference) where status is 'requested' or 'completed'."""
        raise NotImplementedError


def to_subunits(amount):
    """GH₵ 12.50 -> 1250 pesewas."""
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def from_subunits(value):
    return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))
