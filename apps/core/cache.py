from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlencode

from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response

# ── Family constants ────────────────────────────────────────────────
ORG_CACHE       = 'organizations'
PROJECT_CACHE   = 'projects'
SHOP_CACHE      = 'shops'
QUIZ_POOL_CACHE = 'quiz-pool'
SCHOOL_CACHE    = 'schools'

# Internal key prefixes
_VERSION_PREFIX = 'vcv'   # "view-cache-version"
_KEY_PREFIX     = 'vc'    # "view-cache"

# Version keys never expire — if they did, a key expiring mid-traffic
# would reset the version to 1 and cause every old (now-stale) cache
# entry to become "current" again, serving outdated data.
_VERSION_TTL = None


# ── Version helpers ─────────────────────────────────────────────────

def _version_key(family: str) -> str:
    return f'{_VERSION_PREFIX}:{family}'


def _get_version(family: str) -> int:
    """
    Return the current cache version for *family*.
    Uses add() so the initial write is atomic — no get-then-add race.
    """
    key = _version_key(family)
    cache.add(key, 1, _VERSION_TTL)   # no-op if key already exists
    return int(cache.get(key))         # always a valid int after add()


def invalidate_cache_family(family: str) -> None:
    """
    Bump the version number atomically.
    incr() is a single Redis command — safe under concurrent invalidations.
    Falls back to set(2) only when the key genuinely doesn't exist yet.
    """
    key = _version_key(family)
    try:
        cache.incr(key)
    except ValueError:
        # Key missing (e.g. Redis was flushed). Re-initialise at 2 so any
        # lingering v1 responses are never matched by new requests.
        cache.set(key, 2, _VERSION_TTL)


def invalidate_cache_families(*families: str) -> None:
    for family in families:
        invalidate_cache_family(family)


# ── Key construction ────────────────────────────────────────────────

def _normalize_query_string(request) -> str:
    """
    Sort query params so ?b=2&a=1 and ?a=1&b=2 resolve to the same key.
    Without this, every unique param ordering gets its own Redis entry.
    """
    params = parse_qs(request.META.get('QUERY_STRING', ''))
    return urlencode(sorted(params.items()))


def _build_cache_key(request, family: str, vary_on: str | None = None) -> str:
    version  = _get_version(family)
    scope    = f':{vary_on}' if vary_on else ''
    path     = request.path                    # excludes query string
    qs       = _normalize_query_string(request)
    full_url = f'{request.scheme}://{request.get_host()}{path}?{qs}'
    return f'{_KEY_PREFIX}:{family}:v{version}{scope}:{full_url}'


# ── Public interface ────────────────────────────────────────────────

def cached_response(
    request,
    family: str,
    ttl: int,
    builder: Callable[[], Response],
    *,
    vary_on: str | None = None,
) -> Response:
    """
    Return a cached Response if available, otherwise call *builder*,
    cache the result on HTTP 200, and return it.

    Only 200 responses are cached — errors and redirects are never stored.
    """
    key  = _build_cache_key(request, family, vary_on=vary_on)
    data = cache.get(key)

    if data is not None:
        return Response(data)

    response = builder()

    if response.status_code == 200:
        cache.set(key, response.data, ttl)

    return response
