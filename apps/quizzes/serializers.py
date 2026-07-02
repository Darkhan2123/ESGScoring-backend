"""
Input / output DTOs for the quiz endpoints (v2).

Three invariants are enforced exclusively here:

* A question is either True/False (carries ``answer``) or multiple-choice
  (carries ``options[4]`` + ``correct_index``). Both shapes are accepted by
  the bulk endpoint and are validated per-row.
* ``answer``, ``correct_index``, and ``explanation`` are never included in
  any payload sent to a student **before** they submit. They are revealed
  only inside the submit response breakdown.
* Daily-quiz curation is gone -- the only manager flow is question CRUD.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    AttemptQuestion,
    DailyQuiz,
    Question,
    QuizAnswer,
    QuizAttempt,
)


# --- Question serializers --------------------------------------------------


class _MCOptionsField(serializers.ListField):
    """A list of exactly 4 non-empty trimmed strings, MC-only."""

    child = serializers.CharField(max_length=255, allow_blank=False, trim_whitespace=True)
    min_length = 4
    max_length = 4


class QuestionAdminSerializer(serializers.ModelSerializer):
    """Full question payload for managers; reveals the answer fields."""

    created_by_name = serializers.CharField(
        source='created_by.name', read_only=True,
    )

    class Meta:
        model = Question
        fields = [
            'id', 'text', 'question_type',
            'answer', 'options', 'correct_index',
            'explanation',
            'created_by', 'created_by_name', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'created_by_name', 'created_at', 'updated_at']


class QuestionUpdateSerializer(serializers.ModelSerializer):
    """Partial-update payload -- the curator may flip is_active or edit text/explanation.

    Changing the question shape (T/F <-> MC) or the answer once a question
    has been answered by a student would invalidate prior attempts, so this
    serializer keeps it open but the service layer rejects type changes
    when the question has been served.
    """

    options = _MCOptionsField(required=False, allow_null=True)

    class Meta:
        model = Question
        fields = [
            'text', 'question_type',
            'answer', 'options', 'correct_index',
            'explanation', 'is_active',
        ]

    def validate(self, attrs):
        instance = self.instance
        qtype = attrs.get('question_type', instance.question_type if instance else None)
        if qtype == Question.QuestionType.TRUE_FALSE:
            answer = attrs.get('answer', getattr(instance, 'answer', None))
            if answer is None:
                raise serializers.ValidationError(
                    {'answer': 'Required for True/False questions.'},
                )
        elif qtype == Question.QuestionType.MULTIPLE_CHOICE:
            options = attrs.get('options', getattr(instance, 'options', None))
            ci = attrs.get('correct_index', getattr(instance, 'correct_index', None))
            if not isinstance(options, list) or len(options) != 4:
                raise serializers.ValidationError(
                    {'options': 'Must be a list of 4 strings.'},
                )
            if ci not in (0, 1, 2, 3):
                raise serializers.ValidationError(
                    {'correct_index': 'Must be one of 0, 1, 2, 3.'},
                )
        return attrs


class BulkQuestionCreateSerializer(serializers.Serializer):
    """Wrapper for the manager bulk-upload endpoint.

    The per-row shape (T/F vs MC) is inferred by the service layer at
    ``bulk_create_questions``; this serializer only validates that the
    outer envelope is well-formed. Each ``item`` is a plain dict and is
    re-validated by the service for clearer per-row error reporting.
    """

    questions = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )


# --- Daily-quiz serializers (manager analytics only) ----------------------


class DailyQuizListSerializer(serializers.ModelSerializer):
    """Slim list payload for managers browsing past quiz days."""

    attempts_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DailyQuiz
        fields = ['id', 'date', 'attempts_count', 'created_at', 'updated_at']


# --- Student-facing serializers --------------------------------------------


class QuizQuestionPublicSerializer(serializers.ModelSerializer):
    """A served question sent to the student.

    Shape branches on ``question_type``:
      * T/F  -> {id, position, type, text}
      * MC   -> {id, position, type, text, options}

    Never exposes ``answer``, ``correct_index``, or ``explanation``.
    """

    id = serializers.IntegerField(source='question.id')
    position = serializers.IntegerField()
    type = serializers.CharField(source='question.question_type')
    text = serializers.CharField(source='question.text')
    options = serializers.SerializerMethodField()

    class Meta:
        model = AttemptQuestion
        fields = ['id', 'position', 'type', 'text', 'options']

    def get_options(self, obj):
        if obj.question.question_type == Question.QuestionType.MULTIPLE_CHOICE:
            return obj.question.options
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get('options') is None:
            data.pop('options', None)
        return data


class AttemptStatusSerializer(serializers.ModelSerializer):
    """Compact summary of the student's attempt state for ``/today/``."""

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'status', 'started_at', 'deadline_at',
            'submitted_at', 'correct_count', 'points_awarded',
        ]


class AnswerQuestionSerializer(serializers.Serializer):
    """One incoming answer for ``/today/answer/``.

    Exactly one of ``selected_index`` or ``selected_bool`` must be provided;
    the service layer rejects mismatches against the question's type and
    enforces that questions are answered in served order.
    """

    attempt_id = serializers.IntegerField(required=False)
    question_id = serializers.IntegerField()
    selected_index = serializers.IntegerField(
        min_value=0, max_value=3, required=False, allow_null=True,
    )
    selected_bool = serializers.BooleanField(required=False, allow_null=True)

    def validate(self, attrs):
        has_idx = attrs.get('selected_index') is not None
        has_bool = attrs.get('selected_bool') is not None
        if has_idx == has_bool:  # both or neither
            raise serializers.ValidationError(
                'Provide exactly one of selected_index or selected_bool.',
            )
        return attrs


class ForfeitQuizSerializer(serializers.Serializer):
    """Optional reason on ``/today/forfeit/`` (defaults to ``app_background``)."""

    reason = serializers.CharField(max_length=32, required=False, default='app_background')


class MyAttemptSerializer(serializers.ModelSerializer):
    """A row in ``/my-attempts/`` -- includes the date for client grouping."""

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
    """Per-question result row inside the submit response.

    Reveals the correct answer + explanation for the now-locked attempt.
    """

    question_id = serializers.IntegerField()
    type = serializers.CharField(source='question.question_type')
    correct_index = serializers.IntegerField(
        source='question.correct_index', allow_null=True,
    )
    correct_bool = serializers.BooleanField(
        source='question.answer', allow_null=True,
    )
    explanation = serializers.CharField(source='question.explanation')

    class Meta:
        model = QuizAnswer
        fields = [
            'question_id', 'type',
            'selected_index', 'selected_bool',
            'correct_index', 'correct_bool',
            'is_correct', 'explanation',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data['type'] == Question.QuestionType.TRUE_FALSE:
            data.pop('selected_index', None)
            data.pop('correct_index', None)
        else:
            data.pop('selected_bool', None)
            data.pop('correct_bool', None)
        return data
