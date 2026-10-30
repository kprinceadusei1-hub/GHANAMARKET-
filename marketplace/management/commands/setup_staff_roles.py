from django.core.management.base import BaseCommand

from marketplace.staff_roles import ROLES, setup_staff_roles


class Command(BaseCommand):
    help = "Create or refresh the Administrator, Moderator, Support agent and Finance staff groups."

    def handle(self, *args, **options):
        for role, created in setup_staff_roles():
            self.stdout.write(f"{'Created' if created else 'Updated'} {role}: {ROLES[role]['description']}")
        self.stdout.write(
            "Assign a role in the admin under Users > (person) > Groups, and tick 'Staff status'. "
            "Only superusers can do this."
        )
