"""
Role-based DRF permission classes.

Each class simply compares ``request.user.role`` to one of the values defined
on :class:`~apps.users.models.User.Role`. Using the ``TextChoices`` member
(rather than a bare string literal) means any future rename or typo is caught
by static analysis and import-time errors instead of silently locking users
out of endpoints.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .models import User


def _is_role(request: Request, *roles: str) -> bool:
    """Return ``True`` when the authenticated user matches any of ``roles``."""
    user = getattr(request, 'user', None)
    return bool(user and user.is_authenticated and user.role in roles)


class IsAdmin(BasePermission):
    """Allow only super-admin accounts."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.ADMIN)


class IsOrganization(BasePermission):
    """Allow only users that own an organization."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.ORGANIZATION)


class IsStudent(BasePermission):
    """Allow only student accounts."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.STUDENT)


class IsShopOwner(BasePermission):
    """Allow only shop-owner accounts."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.SHOP_OWNER)


class IsAdminOrOrganization(BasePermission):
    """Shared endpoints for admins and organization owners (e.g. leaderboard)."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.ADMIN, User.Role.ORGANIZATION)


class IsAdminOrShopOwner(BasePermission):
    """Shared endpoints for admins and shop owners (e.g. shop management)."""

    def has_permission(self, request, view):
        return _is_role(request, User.Role.ADMIN, User.Role.SHOP_OWNER)
