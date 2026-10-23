"""Deployment checks (run with `manage.py check --deploy`)."""
from django.conf import settings
from django.core.checks import Warning, register


@register(deploy=True)
def shared_cache_for_rate_limits(app_configs, **kwargs):
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if "locmem" in backend.lower():
        return [Warning(
            "Rate limits use a per-process memory cache.",
            hint="Set REDIS_URL so login, registration and message limits are shared by all app workers.",
            id="marketplace.W001",
        )]
    return []
