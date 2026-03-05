from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAdmin, IsOrganization
from .models import Organization
from .serializers import (
    OrganizationSerializer,
    OrganizationListSerializer,
    CreateOrganizationSerializer,
    UpdateOrganizationSerializer,
)


# ─── Public endpoints (any authenticated user) ─────────────────────


class OrganizationListView(APIView):
    """
    GET /api/organizations/
    Lists all active organizations. Any authenticated user.
    Supports ?search=name filter.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orgs = Organization.objects.filter(is_active=True).select_related('owner')
        search = request.query_params.get('search')
        if search:
            orgs = orgs.filter(name__icontains=search)
        return Response(OrganizationListSerializer(orgs, many=True).data)


class OrganizationDetailView(APIView):
    """
    GET /api/organizations/<id>/
    View organization details. Any authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, org_id):
        try:
            org = Organization.objects.select_related('owner').get(
                pk=org_id, is_active=True,
            )
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(OrganizationSerializer(org).data)


# ─── Organization owner endpoints ──────────────────────────────────


class MyOrganizationView(APIView):
    """
    GET   /api/organizations/my/  → org owner views their organization
    PATCH /api/organizations/my/  → org owner updates their organization
    """
    permission_classes = [IsAuthenticated, IsOrganization]

    def get(self, request):
        try:
            org = Organization.objects.select_related('owner').get(
                owner=request.user, is_active=True,
            )
        except Organization.DoesNotExist:
            return Response(
                {'error': 'You do not own any organization.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(OrganizationSerializer(org).data)

    def patch(self, request):
        try:
            org = Organization.objects.get(owner=request.user, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'You do not own any organization.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UpdateOrganizationSerializer(
            org, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(OrganizationSerializer(org).data)


# ─── Admin endpoints ───────────────────────────────────────────────


class AdminCreateOrganizationView(APIView):
    """
    POST /api/organizations/admin/create/
    Admin creates a new organization and assigns an owner.
    Request: { name, description?, owner_id }
    """
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
    """
    GET /api/organizations/admin/
    Admin lists all organizations (including inactive).
    Supports ?is_active=true/false and ?search=name filters.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        orgs = Organization.objects.select_related('owner').all()
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            orgs = orgs.filter(is_active=is_active.lower() == 'true')
        search = request.query_params.get('search')
        if search:
            orgs = orgs.filter(name__icontains=search)
        return Response(OrganizationSerializer(orgs, many=True).data)


class AdminOrganizationDetailView(APIView):
    """
    GET    /api/organizations/admin/<id>/  → view org
    PATCH  /api/organizations/admin/<id>/  → update org
    DELETE /api/organizations/admin/<id>/  → deactivate org
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, org_id):
        try:
            org = Organization.objects.select_related('owner').get(pk=org_id)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(OrganizationSerializer(org).data)

    def patch(self, request, org_id):
        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        allowed_fields = {'name', 'description', 'is_active', 'owner_id'}
        for field, value in request.data.items():
            if field in allowed_fields:
                setattr(org, field, value)
        org.save()
        return Response(OrganizationSerializer(org).data)

    def delete(self, request, org_id):
        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        org.is_active = False
        org.save()
        return Response({'detail': 'Organization deactivated.'})
