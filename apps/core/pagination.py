"""
Project-wide pagination helper for ``APIView`` list endpoints.

DRF's ``DEFAULT_PAGINATION_CLASS`` only activates on ``GenericAPIView``
subclasses. This codebase uses plain ``APIView`` for most list views, so we
expose a thin helper that applies the same ``PageNumberPagination`` defaults
without forcing a wholesale conversion to generics.
"""
from __future__ import annotations

from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response


DEFAULT_PAGE_SIZE = 20


def paginate(
    queryset,
    request: Request,
    serializer_cls,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    context: dict[str, Any] | None = None,
) -> Response:
    """Return a standard DRF paginated ``Response`` for ``queryset``.

    Produces the usual ``{count, next, previous, results}`` envelope so the
    mobile client keeps a single response shape across every list endpoint.
    """
    paginator = PageNumberPagination()
    paginator.page_size = page_size
    page = paginator.paginate_queryset(queryset, request)
    data = serializer_cls(page, many=True, context=context or {}).data
    return paginator.get_paginated_response(data)
