"""
HTTP endpoints for the ``events`` app.

Views are deliberately thin: they read query parameters, assemble a queryset
for the caller's role, delegate state-changing work to :mod:`apps.events.services`,
and serialise the result. Points accounting and capacity checks live in the
service layer so they can be reused by admin actions and management commands.
"""
from __future__ import annotations

from django.db.models import Count, OuterRef, Q, Subquery
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import EventFullError
from apps.core.filters import apply_bool_filter, apply_exact_filter, apply_search
from apps.core.pagination import paginate
from apps.organizations.models import Organization
from apps.users.models import User
from apps.users.permissions import IsAdmin, IsOrganization, IsStudent

from . import services
from .models import Task, TaskParticipation
from .serializers import (
    ApproveRejectSerializer,
    CreateTaskSerializer,
    LeaderboardSerializer,
    MyParticipationSerializer,
    ParticipationRequestSerializer,
    TaskListSerializer,
    TaskOrgSerializer,
    TaskSerializer,
    UpdateTaskSerializer,
    VerifyCodeSerializer,
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


def _annotate_for_student(queryset, user):
    """Attach ``_approved_count`` and ``_registration_status`` annotations.

    The serializer layer reads these without extra queries — used for both the
    list and detail endpoints so the two stay in sync.
    """
    return queryset.annotate(
        _approved_count=Count(
            'participations',
            filter=Q(participations__status__in=[
                TaskParticipation.Status.APPROVED,
                TaskParticipation.Status.COMPLETED,
            ]),
        ),
        _registration_status=Subquery(
            TaskParticipation.objects.filter(
                task=OuterRef('pk'),
                student=user,
            ).values('status')[:1]
        ),
    )


# ─── Public endpoints (any authenticated user) ─────────────────────


class TaskListView(APIView):
    """Role-scoped list of tasks with search + pagination."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role == User.Role.ORGANIZATION:
            org, error = _org_required(request.user)
            if error is not None:
                return error
            tasks = Task.objects.filter(organization=org)
        elif request.user.role == User.Role.ADMIN:
            tasks = Task.objects.all()
        else:
            tasks = Task.objects.filter(is_active=True)

        tasks = tasks.select_related('organization')
        tasks = apply_search(tasks, request, ['title'])
        tasks = _annotate_for_student(tasks, request.user)
        return paginate(
            tasks, request, TaskListSerializer, context={'request': request},
        )


class TaskDetailView(APIView):
    """Read/update/soft-delete a task (update & delete are owner-only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        task = get_object_or_404(
            _annotate_for_student(
                Task.objects.select_related('organization'), request.user,
            ),
            pk=task_id,
        )
        ctx = {'request': request}
        # Owners need the verification code so they can display/share it;
        # everyone else receives the public projection.
        if (
            request.user.role == User.Role.ORGANIZATION
            and task.organization.owner_id == request.user.pk
        ):
            return Response(TaskOrgSerializer(task, context=ctx).data)
        return Response(TaskSerializer(task, context=ctx).data)

    def patch(self, request, task_id):
        if request.user.role != User.Role.ORGANIZATION:
            return Response(
                {'error': 'Only the organization owner can update this task.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        task = get_object_or_404(
            Task.objects.select_related('organization'),
            pk=task_id,
            organization__owner=request.user,
        )
        serializer = UpdateTaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(
            TaskOrgSerializer(
                serializer.save(), context={'request': request},
            ).data,
        )

    def delete(self, request, task_id):
        if request.user.role != User.Role.ORGANIZATION:
            return Response(
                {'error': 'Only the organization owner can deactivate this task.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        task = get_object_or_404(
            Task, pk=task_id, organization__owner=request.user,
        )
        task.is_active = False
        task.save(update_fields=['is_active'])
        return Response({'detail': 'Task deactivated.'})


class LeaderboardView(APIView):
    """Active students ordered by points, with a ``rank`` annotated per row."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        students = User.objects.filter(
            role=User.Role.STUDENT, is_active=True,
        ).order_by('-points', 'full_name')
        students = apply_search(students, request, ['full_name'])

        # Use the paginator explicitly so we can stamp ``rank`` relative to the
        # current page offset — the shared helper doesn't know about ranks.
        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(students, request)
        data = LeaderboardSerializer(page, many=True).data
        start_rank = paginator.page.start_index()
        for i, entry in enumerate(data):
            entry['rank'] = start_rank + i
        return paginator.get_paginated_response(data)


# ─── Student endpoints ─────────────────────────────────────────────


class JoinTaskView(APIView):
    """Student requests to participate in a task (service handles the race)."""

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, task_id):
        task = get_object_or_404(Task, pk=task_id, is_active=True)
        participation = services.request_participation(
            user=request.user, task=task,
        )
        return Response(
            {
                'detail': 'Request submitted successfully.',
                'participation_id': participation.pk,
                'status': participation.status,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyTaskView(APIView):
    """Student submits the task's verification code to claim their points."""

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, task_id):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = get_object_or_404(Task, pk=task_id, is_active=True)

        try:
            services.complete_participation(
                user=request.user,
                task=task,
                code=serializer.validated_data['code'],
            )
        except TaskParticipation.DoesNotExist:
            return Response(
                {'error': 'No approved participation found for this task.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.refresh_from_db(fields=['points'])
        return Response({
            'detail': f'Task completed! You earned {task.points_reward} points.',
            'points_earned': task.points_reward,
            'total_points': request.user.points,
        })


class MyParticipationsView(APIView):
    """Student's own participation history, filterable by ``?status=``."""

    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        participations = TaskParticipation.objects.filter(
            student=request.user,
        ).select_related('task', 'task__organization')
        participations = apply_exact_filter(participations, request, 'status')
        return paginate(
            participations, request, MyParticipationSerializer,
            context={'request': request},
        )


# ─── Organization endpoints ───────────────────────────────────────


class CreateTaskView(APIView):
    """Organization owner creates a task under their own organization."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def post(self, request):
        org, error = _org_required(request.user)
        if error is not None:
            return error
        serializer = CreateTaskSerializer(
            data=request.data, context={'organization': org},
        )
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response(
            TaskOrgSerializer(task, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class TaskRequestsView(APIView):
    """Participation requests for a task owned by the caller."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def get(self, request, task_id):
        task = get_object_or_404(
            Task, pk=task_id, organization__owner=request.user,
        )
        participations = task.participations.select_related('student').all()
        participations = apply_exact_filter(participations, request, 'status')
        return Response(
            ParticipationRequestSerializer(participations, many=True).data,
        )


class ManageRequestView(APIView):
    """Organization owner approves or rejects a participation request."""

    permission_classes = [IsAuthenticated, IsOrganization]

    def patch(self, request, participation_id):
        participation = get_object_or_404(
            TaskParticipation.objects.select_related(
                'task', 'task__organization',
            ),
            pk=participation_id,
            task__organization__owner=request.user,
        )
        serializer = ApproveRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.decide_participation(
            participation=participation,
            new_status=serializer.validated_data['status'],
        )
        return Response(ParticipationRequestSerializer(updated).data)


class StudentHistoryView(APIView):
    """Admin sees the full history; org owners see their org's slice only."""

    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if request.user.role not in (User.Role.ORGANIZATION, User.Role.ADMIN):
            return Response(
                {'error': 'Only organizations and admins can view student history.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        student = get_object_or_404(
            User, pk=student_id, role=User.Role.STUDENT,
        )
        participations = TaskParticipation.objects.filter(
            student=student,
        ).select_related('task', 'task__organization')

        if request.user.role == User.Role.ORGANIZATION:
            org, error = _org_required(request.user)
            if error is not None:
                return error
            participations = participations.filter(task__organization=org)

        return Response(
            MyParticipationSerializer(
                participations, many=True, context={'request': request},
            ).data,
        )


# ─── Admin endpoints ──────────────────────────────────────────────


class AdminTaskListView(APIView):
    """Admin-only paginated list of every task with optional filters."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        tasks = Task.objects.select_related('organization').all()
        tasks = apply_bool_filter(tasks, request, 'is_active')
        tasks = apply_search(tasks, request, ['title'])
        tasks = tasks.annotate(
            _approved_count=Count(
                'participations',
                filter=Q(participations__status__in=[
                    TaskParticipation.Status.APPROVED,
                    TaskParticipation.Status.COMPLETED,
                ]),
            ),
        )
        return paginate(
            tasks, request, TaskSerializer, context={'request': request},
        )


class AdminDeactivateTaskView(APIView):
    """Admin soft-deletes any task regardless of ownership."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def delete(self, request, task_id):
        task = get_object_or_404(Task, pk=task_id)
        task.is_active = False
        task.save(update_fields=['is_active'])
        return Response({'detail': 'Task deactivated.'})
