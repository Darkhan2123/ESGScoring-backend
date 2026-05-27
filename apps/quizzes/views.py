"""
HTTP endpoints for the daily ESG quiz.

The pattern mirrors :mod:`apps.events.views`: thin :class:`APIView` classes,
role-scoped querysets at the top of each handler, and every mutation goes
through :mod:`apps.quizzes.services` so transactional / anti-cheat logic
stays in one place.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.filters import apply_bool_filter, apply_search
from apps.core.pagination import paginate
from apps.users.models import User
from apps.users.permissions import IsAdminOrOrganization, IsStudent

from . import services
from .models import DailyQuiz, Question, QuizAttempt
from .serializers import (
    AttemptAdminSerializer,
    AttemptStatusSerializer,
    BulkQuestionCreateSerializer,
    DailyQuizCreateSerializer,
    DailyQuizListSerializer,
    DailyQuizUpdateSerializer,
    ForfeitQuizSerializer,
    MyAttemptSerializer,
    QuestionAdminSerializer,
    QuestionUpdateSerializer,
    QuizAnswerBreakdownSerializer,
    QuizQuestionPublicSerializer,
    SubmitQuizSerializer,
)


SCORING_CONST = {
    'base_points': services.SUBMIT_BASE_POINTS,
    'points_per_correct': services.POINTS_PER_CORRECT,
}


def _time_limit():
    from django.conf import settings as dj_settings
    return int(getattr(dj_settings, 'QUIZ_TIME_LIMIT_SECONDS', 120))


def _scope_questions_for(user):
    """Org users see only their own pool; admins see all."""
    if user.role == User.Role.ADMIN:
        return Question.objects.all()
    try:
        organization = user.organization
    except Exception:  # noqa: BLE001 — OneToOne reverse raises DoesNotExist
        return Question.objects.none()
    return Question.objects.filter(created_by=organization)


def _scope_daily_quizzes_for(user):
    if user.role == User.Role.ADMIN:
        return DailyQuiz.objects.all()
    try:
        organization = user.organization
    except Exception:  # noqa: BLE001
        return DailyQuiz.objects.none()
    return DailyQuiz.objects.filter(created_by=organization)


# ─── Question pool (managers) ─────────────────────────────────────


class QuestionListView(APIView):
    """List questions scoped to the caller; bulk-create lives on its own URL."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request):
        qs = _scope_questions_for(request.user).select_related('created_by')
        qs = apply_bool_filter(qs, request, 'is_active')
        qs = apply_search(qs, request, ['text'])
        return paginate(qs, request, QuestionAdminSerializer)


class QuestionBulkCreateView(APIView):
    """The only way to create questions — atomic batch upload."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def post(self, request):
        serializer = BulkQuestionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created, ids = services.bulk_create_questions(
            user=request.user,
            items=serializer.validated_data['questions'],
        )
        return Response(
            {'created': created, 'ids': ids},
            status=status.HTTP_201_CREATED,
        )


class QuestionDetailView(APIView):
    """Read / edit / soft-delete a single question owned by the caller."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def _get(self, request, pk):
        return get_object_or_404(_scope_questions_for(request.user), pk=pk)

    def get(self, request, pk):
        return Response(QuestionAdminSerializer(self._get(request, pk)).data)

    def patch(self, request, pk):
        question = self._get(request, pk)
        serializer = QuestionUpdateSerializer(
            question, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(QuestionAdminSerializer(question).data)

    def delete(self, request, pk):
        question = self._get(request, pk)
        question.is_active = False
        question.save(update_fields=['is_active', 'updated_at'])
        return Response({'detail': 'Question deactivated.'})


# ─── Daily quiz curation (managers) ───────────────────────────────


class DailyQuizListCreateView(APIView):
    """List scheduled quizzes / schedule a new one."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request):
        qs = _scope_daily_quizzes_for(request.user).order_by('-date')
        return paginate(qs, request, DailyQuizListSerializer)

    def post(self, request):
        serializer = DailyQuizCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quiz = services.create_daily_quiz(
            user=request.user,
            quiz_date=serializer.validated_data['date'],
            question_ids=serializer.validated_data['question_ids'],
        )
        return Response(
            DailyQuizListSerializer(quiz).data,
            status=status.HTTP_201_CREATED,
        )


class DailyQuizDetailView(APIView):
    """Read / edit / delete a daily quiz owned by the caller."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def _get(self, request, pk):
        return get_object_or_404(_scope_daily_quizzes_for(request.user), pk=pk)

    def get(self, request, pk):
        return Response(DailyQuizListSerializer(self._get(request, pk)).data)

    def patch(self, request, pk):
        quiz = self._get(request, pk)
        serializer = DailyQuizUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        quiz = services.update_daily_quiz(
            user=request.user,
            quiz=quiz,
            is_published=serializer.validated_data.get('is_published'),
            question_ids=serializer.validated_data.get('question_ids'),
        )
        return Response(DailyQuizListSerializer(quiz).data)

    def delete(self, request, pk):
        quiz = self._get(request, pk)
        if quiz.attempts.exists():
            return Response(
                {'error': 'Cannot delete a daily quiz with existing attempts.'},
                status=status.HTTP_409_CONFLICT,
            )
        quiz.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DailyQuizAttemptsView(APIView):
    """Paginated list of student attempts for a given daily quiz."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request, pk):
        quiz = get_object_or_404(_scope_daily_quizzes_for(request.user), pk=pk)
        attempts = quiz.attempts.select_related('user').order_by('-started_at')
        return paginate(attempts, request, AttemptAdminSerializer)


# ─── Student-facing endpoints ─────────────────────────────────────


class TodayStatusView(APIView):
    """Status-only payload — never returns the questions themselves."""

    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        quiz, attempt = services.get_today_quiz_for_student(request.user)
        if quiz is None:
            return Response({
                'available': False,
                'daily_quiz_id': None,
                'date': services.local_today().isoformat(),
                'attempt_status': 'not_started',
                'attempt': None,
                'scoring': SCORING_CONST,
                'time_limit_seconds': _time_limit(),
            })

        return Response({
            'available': True,
            'daily_quiz_id': quiz.pk,
            'date': quiz.date.isoformat(),
            'attempt_status': services.attempt_status_value(attempt),
            'attempt': (
                AttemptStatusSerializer(attempt).data if attempt else None
            ),
            'scoring': SCORING_CONST,
            'time_limit_seconds': _time_limit(),
        })


class TodayStartView(APIView):
    """Begin or resume the student's attempt for today."""

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        attempt, quiz, questions, server_now = services.start_daily_quiz(
            user=request.user,
        )
        return Response(
            {
                'daily_quiz_id': quiz.pk,
                'date': quiz.date.isoformat(),
                'attempt_id': attempt.pk,
                'started_at': attempt.started_at,
                'deadline_at': attempt.deadline_at,
                'server_now': server_now,
                'time_limit_seconds': _time_limit(),
                'questions': QuizQuestionPublicSerializer(questions, many=True).data,
                'scoring': SCORING_CONST,
            },
            status=status.HTTP_201_CREATED,
        )


class TodaySubmitView(APIView):
    """Submit answers and receive the score + breakdown."""

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        serializer = SubmitQuizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt, breakdown, points = services.submit_daily_quiz(
            user=request.user,
            attempt_id=serializer.validated_data.get('attempt_id'),
            answers=serializer.validated_data['answers'],
        )
        request.user.refresh_from_db(fields=['points'])
        return Response(
            {
                'detail': 'Quiz submitted.',
                'daily_quiz_id': attempt.daily_quiz_id,
                'correct_count': attempt.correct_count,
                'points_awarded': points,
                'breakdown': QuizAnswerBreakdownSerializer(breakdown, many=True).data,
                'scoring': SCORING_CONST,
                'total_points': request.user.points,
            },
            status=status.HTTP_201_CREATED,
        )


class TodayForfeitView(APIView):
    """Locks today's in-progress attempt at 0 points (called on app-background)."""

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        serializer = ForfeitQuizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.forfeit_daily_quiz(
            user=request.user,
            reason=serializer.validated_data.get('reason', 'app_background'),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyAttemptsView(APIView):
    """Student's quiz history, newest first; ``?status=`` filter supported."""

    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        qs = (
            QuizAttempt.objects
            .filter(user=request.user)
            .select_related('daily_quiz')
            .order_by('-started_at')
        )
        status_q = request.query_params.get('status')
        if status_q:
            qs = qs.filter(status=status_q)
        return paginate(qs, request, MyAttemptSerializer)
