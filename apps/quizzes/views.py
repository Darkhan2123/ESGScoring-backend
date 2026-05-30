"""
HTTP endpoints for the daily ESG quiz (v2).

Thin :class:`APIView` classes; every mutation goes through
:mod:`apps.quizzes.services` so transactional / anti-cheat logic stays
in one place.

Endpoints:
  * Manager (admin / org): question pool CRUD + daily-quiz analytics.
  * Student: status, start, submit, forfeit, history.

The manager surface no longer schedules daily quizzes by hand -- the
server creates them lazily when the first student plays. See
``apps.quizzes.services.start_daily_quiz``.
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
    DailyQuizListSerializer,
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
    except Exception:  # noqa: BLE001 -- OneToOne reverse raises DoesNotExist
        return Question.objects.none()
    return Question.objects.filter(created_by=organization)


# --- Question pool (managers) ---------------------------------------------


class QuestionListView(APIView):
    """List questions scoped to the caller; bulk-create lives on its own URL."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request):
        qs = _scope_questions_for(request.user).select_related('created_by')
        qs = apply_bool_filter(qs, request, 'is_active')
        qs = apply_search(qs, request, ['text'])
        return paginate(qs, request, QuestionAdminSerializer)


class QuestionBulkCreateView(APIView):
    """The only way to create questions -- atomic batch upload (T/F + MC)."""

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


# --- Daily quiz analytics (managers, read-only) ---------------------------


class DailyQuizListView(APIView):
    """Read-only list of past quiz days with attempt counts."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request):
        qs = DailyQuiz.objects.all().order_by('-date')
        return paginate(qs, request, DailyQuizListSerializer)


class DailyQuizAttemptsView(APIView):
    """Paginated list of student attempts for a given daily quiz."""

    permission_classes = [IsAuthenticated, IsAdminOrOrganization]

    def get(self, request, pk):
        quiz = get_object_or_404(DailyQuiz.objects.all(), pk=pk)
        attempts = quiz.attempts.select_related('user').order_by('-started_at')
        return paginate(attempts, request, AttemptAdminSerializer)


# --- Student-facing endpoints ---------------------------------------------


class TodayStatusView(APIView):
    """Status-only payload -- never returns the questions themselves."""

    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        info = services.get_today_status_for_student(request.user)
        attempt = info['attempt']
        return Response({
            'available': info['available'],
            'daily_quiz_id': info['daily_quiz_id'],
            'date': info['date'],
            'reason': info['reason'],
            'attempt_status': services.attempt_status_value(attempt),
            'attempt': (
                AttemptStatusSerializer(attempt).data if attempt else None
            ),
            'scoring': SCORING_CONST,
            'time_limit_seconds': _time_limit(),
        })


class TodayStartView(APIView):
    """Begin or resume the student's attempt for today.

    The first call of the day for any student auto-creates today's
    :class:`DailyQuiz` row; this student gets 3 random questions
    served via :class:`AttemptQuestion`.
    """

    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        attempt, quiz, served, server_now = services.start_daily_quiz(
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
                'questions': QuizQuestionPublicSerializer(served, many=True).data,
                'scoring': SCORING_CONST,
            },
            status=status.HTTP_201_CREATED,
        )


class TodaySubmitView(APIView):
    """Submit answers and receive the score + breakdown.

    The breakdown reveals the correct answer + explanation per question.
    """

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
                'breakdown': QuizAnswerBreakdownSerializer(
                    breakdown, many=True,
                ).data,
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
