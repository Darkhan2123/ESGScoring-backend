"""
Input / output DTOs for the quiz endpoints.

Two invariants are enforced exclusively here:

* ``Question.options`` must be a list of four non-empty strings, and
  ``correct_index`` must lie in 0..3.
* ``correct_index`` is **never** included in any serializer used before a
  student locks their answers in (``/today/`` and ``/today/start/``); it is
  revealed only inside the submit response.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    DailyQuiz,
    DailyQuizQuestion,
    Question,
    QuizAnswer,
    QuizAttempt,
)


# ─── Question serializers ─────────────────────────────────────────


class QuestionOptionsField(serializers.ListField):
    """A list of exactly 4 non-empty trimmed strings."""

    child = serializers.CharField(max_length=255, allow_blank=False, trim_whitespace=True)
    min_length = 4
    max_length = 4


class QuestionAdminSerializer(serializers.ModelSerializer):
    """Full question payload for managers (includes ``correct_index``)."""

    options = QuestionOptionsField()
    created_by_name = serializers.CharField(
        source='created_by.name', read_only=True,
    )

    class Meta:
        model = Question
        fields = [
            'id', 'text', 'options', 'correct_index',
            'created_by', 'created_by_name', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'created_by_name', 'created_at', 'updated_at']

    def validate_correct_index(self, value):
        if value not in (0, 1, 2, 3):
            raise serializers.ValidationError('Must be 0, 1, 2 or 3.')
        return value


class QuestionUpdateSerializer(serializers.ModelSerializer):
    """Partial-update payload — only the fields curators are allowed to edit."""

    options = QuestionOptionsField(required=False)

    class Meta:
        model = Question
        fields = ['text', 'options', 'correct_index', 'is_active']

    def validate_correct_index(self, value):
        if value not in (0, 1, 2, 3):
            raise serializers.ValidationError('Must be 0, 1, 2 or 3.')
        return value


class BulkQuestionItemSerializer(serializers.Serializer):
    """One row inside the bulk-create payload."""

    text = serializers.CharField()
    options = QuestionOptionsField()
    correct_index = serializers.IntegerField(min_value=0, max_value=3)


class BulkQuestionCreateSerializer(serializers.Serializer):
    """Wrapper for the manager bulk-dump endpoint."""

    questions = serializers.ListField(
        child=BulkQuestionItemSerializer(),
        allow_empty=False,
    )


# ─── Daily-quiz serializers ───────────────────────────────────────


class DailyQuizListSerializer(serializers.ModelSerializer):
    """Slim list payload for managers browsing scheduled quizzes."""

    question_ids = serializers.SerializerMethodField()
    attempts_count = serializers.SerializerMethodField()

    class Meta:
        model = DailyQuiz
        fields = [
            'id', 'date', 'created_by', 'is_published',
            'question_ids', 'attempts_count', 'created_at', 'updated_at',
        ]

    def get_question_ids(self, obj):
        return list(
            obj.quiz_questions.order_by('position').values_list('question_id', flat=True),
        )

    def get_attempts_count(self, obj):
        return obj.attempts.count()


class DailyQuizCreateSerializer(serializers.Serializer):
    """Manager schedules a daily quiz with three ordered question ids."""

    date = serializers.DateField()
    question_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=3,
        max_length=3,
    )

    def validate_question_ids(self, value):
        if len(set(value)) != 3:
            raise serializers.ValidationError('Question ids must be distinct.')
        return value


class DailyQuizUpdateSerializer(serializers.Serializer):
    """Partial update — only swap order/questions or toggle publish flag.

    The service rejects any change once a student has started an attempt.
    """

    is_published = serializers.BooleanField(required=False)
    question_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=3,
        max_length=3,
        required=False,
    )

    def validate_question_ids(self, value):
        if len(set(value)) != 3:
            raise serializers.ValidationError('Question ids must be distinct.')
        return value


# ─── Student-facing serializers ───────────────────────────────────


class QuizQuestionPublicSerializer(serializers.ModelSerializer):
    """Question payload sent to a student — never includes ``correct_index``."""

    position = serializers.IntegerField()
    id = serializers.IntegerField(source='question.id')
    text = serializers.CharField(source='question.text')
    options = serializers.JSONField(source='question.options')

    class Meta:
        model = DailyQuizQuestion
        fields = ['id', 'position', 'text', 'options']


class AttemptStatusSerializer(serializers.ModelSerializer):
    """Compact summary of the student's attempt state for ``/today/``."""

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'status', 'started_at', 'deadline_at',
            'submitted_at', 'correct_count', 'points_awarded',
        ]


class SubmitAnswerSerializer(serializers.Serializer):
    """One incoming answer in the submit payload."""

    question_id = serializers.IntegerField()
    selected_index = serializers.IntegerField(min_value=0, max_value=3)


class SubmitQuizSerializer(serializers.Serializer):
    """Student submission for ``/today/submit/``."""

    attempt_id = serializers.IntegerField(required=False)
    answers = serializers.ListField(
        child=SubmitAnswerSerializer(),
        min_length=3,
        max_length=3,
    )


class ForfeitQuizSerializer(serializers.Serializer):
    """Optional reason on ``/today/forfeit/`` (defaults to ``app_background``)."""

    reason = serializers.CharField(max_length=32, required=False, default='app_background')


class MyAttemptSerializer(serializers.ModelSerializer):
    """A row in ``/my-attempts/`` — includes the date for client grouping."""

    date = serializers.DateField(source='daily_quiz.date', read_only=True)
    daily_quiz_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'daily_quiz_id', 'date', 'status',
            'correct_count', 'points_awarded',
            'started_at', 'deadline_at', 'submitted_at',
        ]


class AttemptAdminSerializer(serializers.ModelSerializer):
    """Manager view of one attempt on a given daily quiz."""

    user_id = serializers.IntegerField(read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'user_id', 'user_name', 'user_email',
            'status', 'correct_count', 'points_awarded',
            'started_at', 'deadline_at', 'submitted_at', 'forfeit_reason',
        ]


class QuizAnswerBreakdownSerializer(serializers.ModelSerializer):
    """Per-question result row inside the submit response."""

    question_id = serializers.IntegerField()
    correct_index = serializers.IntegerField(source='question.correct_index')

    class Meta:
        model = QuizAnswer
        fields = ['question_id', 'selected_index', 'correct_index', 'is_correct']
