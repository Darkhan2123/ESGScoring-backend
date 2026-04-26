"""
Lightweight query-parameter helpers for ``APIView``-based list endpoints.

DRF's filter backends (``DjangoFilterBackend``, ``SearchFilter``) only run on
generic views. Rather than rewrite every endpoint as a generic, we provide a
small set of helpers that cover the cases this codebase actually uses:

* boolean flags (``?is_active=true``) — parsed leniently so ``1``/``0``/
  ``yes``/``no`` all behave consistently;
* case-insensitive substring search across one or more fields;
* exact-match filters for enum-backed columns like ``status`` or ``role``.
"""
from __future__ import annotations

from typing import Iterable

from django.db.models import Q
from rest_framework.request import Request


_TRUTHY = frozenset({'1', 'true', 't', 'yes', 'y', 'on'})
_FALSY = frozenset({'0', 'false', 'f', 'no', 'n', 'off'})


def parse_bool(value: str | None) -> bool | None:
    """Return ``True``/``False``/``None`` for common string representations."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return None


def apply_search(queryset, request: Request, fields: Iterable[str], param: str = 'search'):
    """Filter ``queryset`` with ``icontains`` across ``fields``.

    Multiple fields are OR'd together so ``?search=abc`` matches any of them.
    """
    term = request.query_params.get(param)
    if not term:
        return queryset
    lookup = Q()
    for field in fields:
        lookup |= Q(**{f'{field}__icontains': term})
    return queryset.filter(lookup)


def apply_bool_filter(queryset, request: Request, param: str, field: str | None = None):
    """Filter ``queryset`` by a boolean query-param.

    ``field`` defaults to ``param`` when omitted.
    """
    value = parse_bool(request.query_params.get(param))
    if value is None:
        return queryset
    return queryset.filter(**{field or param: value})


def apply_exact_filter(queryset, request: Request, param: str, field: str | None = None):
    """Filter ``queryset`` by an exact value — typically an enum column."""
    value = request.query_params.get(param)
    if not value:
        return queryset
    return queryset.filter(**{field or param: value})
