import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create the first admin account from DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL and "
        "DJANGO_SUPERUSER_PASSWORD. Does nothing if the account exists; never changes an existing password."
    )

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        if not (username and email and password):
            self.stdout.write("No DJANGO_SUPERUSER_* settings; skipping admin account creation.")
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Admin account '{username}' already exists; left unchanged.")
            return
        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created admin account '{username}'."))
