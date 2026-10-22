from django.core.management.base import BaseCommand

from commerce.services import expire_stale_checkouts


class Command(BaseCommand):
    help = "Expire unpaid checkouts past their payment window and return reserved stock. Run every few minutes."

    def handle(self, *args, **options):
        expired = expire_stale_checkouts()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} unpaid checkout(s)."))
