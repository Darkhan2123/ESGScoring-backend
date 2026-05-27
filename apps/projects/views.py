"""
HTTP endpoints for the ``projects`` app.

Projects are a lightweight sibling of tasks: the organization owner publishes a
short description plus a Google Forms link, and students browse the catalogue.
Applicants are handled outside the platform — Google Forms owns the workflow.

Views are split into three audiences (public read, organization owner CRUD,
admin override) matching the pattern in :mod:`apps.organizations.views`.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.filters import apply_bool_filter, apply_exact_filter, apply_search
from apps.core.pagination import paginate
from apps.organizations.models import Organization
from apps.users.permissions import IsAdmin, IsOrganization

from .models import Project
from .serializers import (
    AdminUpdateProjectSerializer,
    CreateProjectSerializer,
    ProjectListSerializer,
    ProjectSerializer,
    UpdateProjectSerializer,
)


# ─── Helpers ───────────────────────────────────────────────────────


def _user_org(user):
    """Return ``user.organization`` or ``None`` when the owner has none yet."""
    try:
        return user.organization
    except Organization.DoesNotExist:
        return None


def _org_required(user):
    """Return ``(organization, None)`` or ``(None, 404 response)``."""
    org = _user_org(user)
    if org is None:
        return None, Response(
            {'error': 'You do not have an organization assigned.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return org, None


# ─── Public endpoints (any authenticated user) ─────────────────────


class ProjectListView(APIView):
    """Public catalogue of active projects across all active organizations."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        projects = (
            Project.objects
            .filter(is_active=True, organization__is_active=True)
            .select_related('organization')
        )
        projects = apply_exact_filter(projects, request, 'organization')
        projects = apply_search(projects, request, ['title'])
        return paginate(projects, request, ProjectListSerializer)


class ProjectDetailView(APIView):
    """Public read-only view of one active project."""

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(
            Project.objects.select_related('organization'),
            pk=project_id,
            is_active=True,
            organization__is_active=True,
        )
        return Response(ProjectSerializer(project).data)


# ─── Organization owner endpoints ──────────────────────────────────


class MyProjectsView(APIView):
    """List the caller's projects and create new ones under their org."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def get(self, request):
        org, error = _org_required(request.user)
        if error is not None:
            return error
        projects = (
            Project.objects
            .filter(organization=org)
            .select_related('organization')
        )
        projects = apply_bool_filter(projects, request, 'is_active')
        projects = apply_search(projects, request, ['title'])
        return paginate(projects, request, ProjectListSerializer)

    def post(self, request):
        org, error = _org_required(request.user)
        if error is not None:
            return error
        serializer = CreateProjectSerializer(
            data=request.data, context={'organization': org},
        )
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        return Response(
            ProjectSerializer(project).data,
            status=status.HTTP_201_CREATED,
        )


class MyProjectDetailView(APIView):
    """Owner-scoped read/update/soft-delete of a single project."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def _get(self, request, project_id):
        return get_object_or_404(
            Project.objects.select_related('organization'),
            pk=project_id,
            organization__owner=request.user,
        )

    def get(self, request, project_id):
        return Response(ProjectSerializer(self._get(request, project_id)).data)

    def patch(self, request, project_id):
        project = self._get(request, project_id)
        serializer = UpdateProjectSerializer(
            project, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(ProjectSerializer(serializer.save()).data)

    def delete(self, request, project_id):
        project = self._get(request, project_id)
        project.is_active = False
        project.save(update_fields=['is_active'])
        return Response({'detail': 'Project deactivated.'})


# ─── Admin endpoints ───────────────────────────────────────────────


class AdminProjectListView(APIView):
    """Admin-only paginated list with ``?is_active=``, ``?organization=``, ``?search=``."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        projects = Project.objects.select_related('organization').all()
        projects = apply_bool_filter(projects, request, 'is_active')
        projects = apply_exact_filter(projects, request, 'organization')
        projects = apply_search(projects, request, ['title'])
        return paginate(projects, request, ProjectSerializer)


class AdminProjectDetailView(APIView):
    """Admin read/update/soft-delete of any project."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def _get(self, project_id):
        return get_object_or_404(
            Project.objects.select_related('organization'), pk=project_id,
        )

    def get(self, request, project_id):
        return Response(ProjectSerializer(self._get(project_id)).data)

    def patch(self, request, project_id):
        project = self._get(project_id)
        serializer = AdminUpdateProjectSerializer(
            project, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(ProjectSerializer(serializer.save()).data)

    def delete(self, request, project_id):
        project = self._get(project_id)
        project.is_active = False
        project.save(update_fields=['is_active'])
        return Response({'detail': 'Project deactivated.'})
