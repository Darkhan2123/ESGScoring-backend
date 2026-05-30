"""Shared serializer helpers reused across apps."""
from __future__ import annotations


def absolute_url(file, request):
    """Return the absolute URL for an uploaded file, or ``None`` when empty.

    Falls back to the relative URL when no ``request`` is in serializer
    context (mirrors the pattern used by the organization logo field).
    """
    if not file:
        return None
    url = file.url
    return request.build_absolute_uri(url) if request else url


def resolve_image(obj, request):
    """Resolve an object's own image, falling back to its org logo.

    Used by events and projects so a card always has a picture: the
    event/project photo when uploaded, otherwise the posting org's avatar.
    """
    own = absolute_url(getattr(obj, 'image', None), request)
    if own:
        return own
    org = getattr(obj, 'organization', None)
    return absolute_url(getattr(org, 'logo', None), request) if org else None
