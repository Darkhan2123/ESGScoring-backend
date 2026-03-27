from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import (
    DuplicateRequestError,
    EventFullError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
)
from apps.organizations.models import Organization
from apps.users.models import User
from apps.users.permissions import IsAdmin, IsOrganization, IsStudent
from .models import Task, TaskParticipation
from .serializers import (
    TaskListSerializer,
    TaskSerializer,
    TaskOrgSerializer,
    CreateTaskSerializer,
    UpdateTaskSerializer,
    ParticipationRequestSerializer,
    MyParticipationSerializer,
    ApproveRejectSerializer,
    VerifyCodeSerializer,
    LeaderboardSerializer,
)


def _get_org_or_404(user):
    """Get the organization owned by this user, or return 404 response."""
    try:
        return user.organization
    except Organization.DoesNotExist:
        return None


# ─── Public endpoints (any authenticated user) ─────────────────────


class TaskListView(APIView):
    """
    GET /api/events/tasks/
    Students: all active tasks.
    Org owners: their organization's tasks.
    Admins: all tasks.
    Supports ?search=title filter.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role == User.Role.ORGANIZATION:
            org = _get_org_or_404(request.user)
            if org is None:
                return Response(
                    {'error': 'You do not have an organization assigned.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            tasks = Task.objects.filter(
                organization=org,
            ).select_related('organization')
        elif request.user.role == User.Role.ADMIN:
            tasks = Task.objects.select_related('organization').all()
        else:
            tasks = Task.objects.filter(
                is_active=True,
            ).select_related('organization')

        search = request.query_params.get('search')
        if search:
            tasks = tasks.filter(title__icontains=search)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(tasks, request)
        return paginator.get_paginated_response(
            TaskListSerializer(page, many=True).data,
        )


class TaskDetailView(APIView):
    """
    GET    /api/events/tasks/<id>/  → task detail (any auth user)
    PATCH  /api/events/tasks/<id>/  → update task (org owner only)
    DELETE /api/events/tasks/<id>/  → deactivate task (org owner only)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        try:
            task = Task.objects.select_related('organization').get(pk=task_id)
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Org owner sees verification code, others don't
        if (
            request.user.role == User.Role.ORGANIZATION
            and task.organization.owner_id == request.user.pk
        ):
            return Response(TaskOrgSerializer(task).data)
        return Response(TaskSerializer(task).data)

    def patch(self, request, task_id):
        if request.user.role != User.Role.ORGANIZATION:
            return Response(
                {'error': 'Only the organization owner can update this task.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            task = Task.objects.select_related('organization').get(
                pk=task_id, organization__owner=request.user,
            )
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UpdateTaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_task = serializer.save()
        return Response(TaskOrgSerializer(updated_task).data)

    def delete(self, request, task_id):
        if request.user.role != User.Role.ORGANIZATION:
            return Response(
                {'error': 'Only the organization owner can deactivate this task.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            task = Task.objects.get(
                pk=task_id, organization__owner=request.user,
            )
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        task.is_active = False
        task.save()
        return Response({'detail': 'Task deactivated.'})


class LeaderboardView(APIView):
    """
    GET /api/events/leaderboard/
    Students ranked by points. Any authenticated user.
    Supports ?search=name filter.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        students = User.objects.filter(
            role=User.Role.STUDENT, is_active=True,
        ).order_by('-points', 'full_name')

        search = request.query_params.get('search')
        if search:
            students = students.filter(full_name__icontains=search)

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
    """
    POST /api/events/tasks/<id>/join/
    Student requests to join a task.
    """
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, task_id):
        try:
            task = Task.objects.get(pk=task_id, is_active=True)
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if task.is_full:
            raise EventFullError('This task has reached the maximum number of participants.')

        if TaskParticipation.objects.filter(
            task=task, student=request.user,
        ).exists():
            raise DuplicateRequestError('You have already applied to this task.')

        participation = TaskParticipation.objects.create(
            task=task, student=request.user,
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
    """
    POST /api/events/tasks/<id>/verify/
    Student submits verification code → points awarded atomically.
    """
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, task_id):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']

        try:
            task = Task.objects.get(pk=task_id, is_active=True)
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if task.verification_code != code:
            raise InvalidVerificationCodeError('Invalid verification code.')

        with transaction.atomic():
            try:
                participation = (
                    TaskParticipation.objects
                    .select_for_update()
                    .get(
                        task=task,
                        student=request.user,
                        status=TaskParticipation.Status.APPROVED,
                    )
                )
            except TaskParticipation.DoesNotExist:
                return Response(
                    {'error': 'No approved participation found for this task.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            participation.status = TaskParticipation.Status.COMPLETED
            participation.save()

            User.objects.filter(pk=request.user.pk).update(
                points=F('points') + task.points_reward,
            )

        request.user.refresh_from_db()
        return Response({
            'detail': f'Task completed! You earned {task.points_reward} points.',
            'points_earned': task.points_reward,
            'total_points': request.user.points,
        })


class MyParticipationsView(APIView):
    """
    GET /api/events/my-participations/
    Student views their own task participations.
    Supports ?status=pending/approved/rejected/completed filter.
    """
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        participations = TaskParticipation.objects.filter(
            student=request.user,
        ).select_related('task', 'task__organization')

        task_status = request.query_params.get('status')
        if task_status:
            participations = participations.filter(status=task_status)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(participations, request)
        return paginator.get_paginated_response(
            MyParticipationSerializer(page, many=True).data,
        )


# ─── Organization endpoints ───────────────────────────────────────


class CreateTaskView(APIView):
    """
    POST /api/events/tasks/create/
    Organization creates a new task.
    Verification code is auto-generated.
    """
    permission_classes = [IsAuthenticated, IsOrganization]

    def post(self, request):
        org = _get_org_or_404(request.user)
        if org is None:
            return Response(
                {'error': 'You do not have an organization assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CreateTaskSerializer(
            data=request.data, context={'organization': org},
        )
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response(
            TaskOrgSerializer(task).data,
            status=status.HTTP_201_CREATED,
        )


class TaskRequestsView(APIView):
    """
    GET /api/events/tasks/<id>/requests/
    Org views participation requests for their own task.
    Supports ?status=pending/approved/rejected/completed filter.
    """
    permission_classes = [IsAuthenticated, IsOrganization]

    def get(self, request, task_id):
        try:
            task = Task.objects.get(
                pk=task_id, organization__owner=request.user,
            )
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        participations = task.participations.select_related('student').all()

        req_status = request.query_params.get('status')
        if req_status:
            participations = participations.filter(status=req_status)

        return Response(
            ParticipationRequestSerializer(participations, many=True).data,
        )


class ManageRequestView(APIView):
    """
    PATCH /api/events/requests/<id>/
    Org approves or rejects a participation request.
    Request: { status: "approved" | "rejected" }
    """
    permission_classes = [IsAuthenticated, IsOrganization]

    def patch(self, request, participation_id):
        try:
            participation = (
                TaskParticipation.objects
                .select_related('task', 'task__organization')
                .get(
                    pk=participation_id,
                    task__organization__owner=request.user,
                )
            )
        except TaskParticipation.DoesNotExist:
            return Response(
                {'error': 'Participation request not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ApproveRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if not participation.can_transition_to(new_status):
            raise InvalidStateTransitionError(
                f"Cannot change status from '{participation.status}' to '{new_status}'."
            )

        if (
            new_status == TaskParticipation.Status.APPROVED
            and participation.task.is_full
        ):
            raise EventFullError(
                'This task has reached the maximum number of participants.'
            )

        participation.status = new_status
        participation.save()
        return Response(ParticipationRequestSerializer(participation).data)


class StudentHistoryView(APIView):
    """
    GET /api/events/students/<id>/history/
    Org views a student's task history (scoped to their org only).
    Admin views all task history for a student.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if request.user.role not in (User.Role.ORGANIZATION, User.Role.ADMIN):
            return Response(
                {'error': 'Only organizations and admins can view student history.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            student = User.objects.get(
                pk=student_id, role=User.Role.STUDENT,
            )
        except User.DoesNotExist:
            return Response(
                {'error': 'Student not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        participations = TaskParticipation.objects.filter(
            student=student,
        ).select_related('task', 'task__organization')

        if request.user.role == User.Role.ORGANIZATION:
            org = _get_org_or_404(request.user)
            if org is None:
                return Response(
                    {'error': 'You do not have an organization assigned.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            participations = participations.filter(task__organization=org)

        return Response(
            MyParticipationSerializer(participations, many=True).data,
        )


# ─── Admin endpoints ──────────────────────────────────────────────


class AdminTaskListView(APIView):
    """
    GET /api/events/admin/tasks/
    Admin lists all tasks (including inactive).
    Supports ?is_active=true/false and ?search=title filters.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        tasks = Task.objects.select_related('organization').all()

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            tasks = tasks.filter(is_active=is_active.lower() == 'true')

        search = request.query_params.get('search')
        if search:
            tasks = tasks.filter(title__icontains=search)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(tasks, request)
        return paginator.get_paginated_response(
            TaskSerializer(page, many=True).data,
        )


class AdminDeactivateTaskView(APIView):
    """
    DELETE /api/events/admin/tasks/<id>/
    Admin deactivates any task.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def delete(self, request, task_id):
        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            return Response(
                {'error': 'Task not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        task.is_active = False
        task.save()
        return Response({'detail': 'Task deactivated.'})
