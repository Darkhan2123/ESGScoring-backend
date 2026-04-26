"""
HTTP endpoints for the ``organizations`` app.

Organizations are the event-producing entity of the platform: each one is owned
by exactly one user with the ``ORGANIZATION`` role, and any task/event hangs
off the organization FK. These views split cleanly into three audiences —
public (read-only), the owner (self-service PATCH), and admin (full CRUD +
soft-delete).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.filters import apply_bool_filter, apply_search
from apps.core.pagination import paginate
from apps.users.permissions import IsAdmin, IsOrganization

from .models import Organization
from .serializers import (
    AdminUpdateOrganizationSerializer,
    CreateOrganizationSerializer,
    OrganizationListSerializer,
    OrganizationSerializer,
    UpdateOrganizationSerializer,
)


# ─── Public endpoints (any authenticated user) ─────────────────────


class OrganizationListView(APIView):
    """Public catalogue of active organizations."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        orgs = Organization.objects.filter(is_active=True).select_related('owner')
        orgs = apply_search(orgs, request, ['name'])
        return Response(OrganizationListSerializer(orgs, many=True).data)


class OrganizationDetailView(APIView):
    """Public read-only view of one active organization."""

    permission_classes = [IsAuthenticated]

    def get(self, request, org_id):
        org = get_object_or_404(
            Organization.objects.select_related('owner'),
            pk=org_id,
            is_active=True,
        )
        return Response(OrganizationSerializer(org).data)


# ─── Organization owner endpoints ──────────────────────────────────


class MyOrganizationView(APIView):
    """Self-service read/patch for the authenticated organization owner."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def _get_owned(self, user):
        return get_object_or_404(
            Organization.objects.select_related('owner'),
            owner=user,
            is_active=True,
        )

    def get(self, request):
        org = self._get_owned(request.user)
        return Response(OrganizationSerializer(org).data)

    def patch(self, request):
        org = self._get_owned(request.user)
        serializer = UpdateOrganizationSerializer(
            org, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(OrganizationSerializer(serializer.save()).data)


# ─── Admin endpoints ───────────────────────────────────────────────


class AdminCreateOrganizationView(APIView):
    """Admin creates an organization and assigns an owner."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = CreateOrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = serializer.save()
        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )


class AdminOrganizationListView(APIView):
    """Admin-only paginated list with ``?is_active=`` and ``?search=`` filters."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        orgs = Organization.objects.select_related('owner').all()
        orgs = apply_bool_filter(orgs, request, 'is_active')
        orgs = apply_search(orgs, request, ['name'])
        return paginate(orgs, request, OrganizationSerializer)


class AdminOrganizationDetailView(APIView):
    """Admin read/update/soft-delete of any organization."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def _get(self, org_id):
        return get_object_or_404(
            Organization.objects.select_related('owner'), pk=org_id,
        )

    def get(self, request, org_id):
        return Response(OrganizationSerializer(self._get(org_id)).data)

    def patch(self, request, org_id):
        org = self._get(org_id)
        serializer = AdminUpdateOrganizationSerializer(
            org, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(OrganizationSerializer(serializer.save()).data)

    def delete(self, request, org_id):
        org = self._get(org_id)
        org.is_active = False
        org.save(update_fields=['is_active'])
        return Response({'detail': 'Organization deactivated.'})
