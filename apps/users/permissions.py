from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'admin'


class IsOrganization(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'organization'


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'student'


class IsShopOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'shop_owner'


class IsAdminOrOrganization(BasePermission):
    """For endpoints shared between admin and org admins (e.g. viewing leaderboard)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ('admin', 'organization')


class IsAdminOrShopOwner(BasePermission):
    """For shop management endpoints."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ('admin', 'shop_owner')
