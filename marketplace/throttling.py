"""Small cache-backed rate limits for abuse-prone actions (login, messaging, reports).

Uses Django's configured cache, so limits are per-process with the default
local-memory cache and shared across workers once a shared cache (e.g. Redis)
is configured for production.
"""
import hashlib

from django.core.cache import cache


def client_ip(request):
    # Only trust X-Forwarded-For when explicitly running behind a known proxy.
    from django.conf import settings

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _key(scope, identity):
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"throttle:{scope}:{digest}"


def is_limited(scope, identity, limit):
    """Return True when ``identity`` has reached ``limit`` attempts in the current window."""
    return cache.get(_key(scope, identity), 0) >= limit


def record_attempt(scope, identity, window_seconds):
    key = _key(scope, identity)
    if cache.add(key, 1, window_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window_seconds)
        return 1


def reset(scope, identity):
    cache.delete(_key(scope, identity))


def hit(scope, identity, limit, window_seconds):
    """Record an attempt and return True when the caller is over the limit."""
    if is_limited(scope, identity, limit):
        return True
    record_attempt(scope, identity, window_seconds)
    return False
