"""Ready-made staff roles for the admin control room.

Super administrators are Django superusers: they alone can grant staff access, edit roles and see
everything. Every other staff member gets one of these groups, so nobody holds more access than
their job needs. ``python manage.py setup_staff_roles`` creates or refreshes them; it only ever sets
the permissions listed here and never touches people's group membership.
"""
from django.contrib.auth.models import Group, Permission

ALL = ("view", "add", "change", "delete")

ROLES = {
    "Administrator": {
        "description": "Runs the marketplace day to day: people, sellers, listings, orders, categories, promotions and support.",
        "permissions": {
            "marketplace": {
                "user": ("view", "change"),
                "sellerverification": ("view", "change"),
                "product": ("view", "change"),  # listings are never deleted from the admin, only removed
                "productphoto": ALL,
                "category": ALL,
                "categoryattribute": ALL,
                "listingreport": ("view", "change"),
                "userreport": ("view", "change"),
                "userblock": ("view",),
                "sellerreview": ("view", "change"),
                "prohibitedterm": ALL,
                "searchterm": ("view", "change"),
                "supportrequest": ("view", "change"),
                "conversation": ("view",),
                "message": ("view",),
                "promotion": ALL,
                "homebanner": ALL,
            },
            "commerce": {
                "order": ("view", "change"),
                "orderissue": ("view", "change"),
                "checkout": ("view",),
                "deliveryoption": ALL,
                "payment": ("view",),
                "refund": ("view",),
            },
            "admin": {"logentry": ("view",)},
        },
    },
    "Moderator": {
        "description": "Reviews listings and reports, and keeps prohibited content off the site.",
        "permissions": {
            "marketplace": {
                "product": ("view", "change"),
                "productphoto": ("view",),
                "category": ("view",),
                "listingreport": ("view", "change"),
                "userreport": ("view", "change"),
                "sellerreview": ("view", "change"),
                "prohibitedterm": ("view", "add", "change"),
                "searchterm": ("view", "change"),
                "user": ("view",),
            },
        },
    },
    "Support agent": {
        "description": "Answers support tickets and looks into order problems. Read-only on people, listings and orders.",
        "permissions": {
            "marketplace": {
                "supportrequest": ("view", "change"),
                "user": ("view",),
                "product": ("view",),
                "userreport": ("view",),
            },
            "commerce": {
                "order": ("view",),
                "orderissue": ("view", "change"),
                "deliveryoption": ("view",),
            },
        },
    },
    "Finance": {
        "description": "Checks payments, reconciles them with the provider and issues refunds.",
        "permissions": {
            "commerce": {
                "order": ("view",),
                "checkout": ("view",),
                "payment": ("view",),
                "paymentevent": ("view",),
                "refund": ("view", "add"),
                "orderissue": ("view",),
            },
        },
    },
}


def role_permissions(role):
    """Permission objects for a role. A missing permission is a coding error, so it raises."""
    wanted = []
    for app_label, models in ROLES[role]["permissions"].items():
        for model, actions in models.items():
            wanted.extend((app_label, f"{action}_{model}") for action in actions)
    found = {
        (perm.content_type.app_label, perm.codename): perm
        for perm in Permission.objects.select_related("content_type").filter(
            content_type__app_label__in={app for app, _ in wanted}
        )
    }
    missing = [f"{app}.{code}" for app, code in wanted if (app, code) not in found]
    if missing:
        raise LookupError(f"Unknown permissions for {role}: {', '.join(missing)}")
    return [found[key] for key in wanted]


def setup_staff_roles():
    """Create or refresh every role so it holds exactly its listed permissions. Returns (name, created) pairs."""
    results = []
    for role in ROLES:
        group, created = Group.objects.get_or_create(name=role)
        group.permissions.set(role_permissions(role))
        results.append((role, created))
    return results
