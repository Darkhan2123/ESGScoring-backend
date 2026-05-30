"""
Models for the daily ESG quiz mini-game (v2).

Five tables back the feature:

* :class:`Question` -- the pool managers curate. Each question is either
  True/False (``question_type=TRUE_FALSE``) or 4-option multiple-choice
  (``question_type=MULTIPLE_CHOICE``). Both shapes carry a free-form
  ``explanation`` that is revealed only after a student submits.
* :class:`DailyQuiz` -- one row per calendar date the moment any student
  plays. Created lazily by the service layer -- no manual curation.
* :class:`QuizAttempt` -- a student's once-per-day session row. Unique on
  ``(user, daily_quiz)`` so leaving the app cannot earn a retry.
* :class:`AttemptQuestion` -- the three questions that were actually
  served to a specific attempt (per-student random pick from the pool).
* :class:`QuizAnswer` -- the student's chosen answer per served question;
  ``is_correct`` is server-computed at submit time.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Question(models.Model):
    """An ESG question.

    Two shapes coexist behind one table; ``question_type`` controls which
    columns are meaningful.
    """

    class QuestionType(models.TextChoices):
        TRUE_FALSE = 'true_false', 'True/False'
        MULTIPLE_CHOICE = 'multiple_choice', 'Multiple choice'

    text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.TRUE_FALSE,
    )
    # TRUE_FALSE only:
    answer = models.BooleanField(null=True, blank=True)
    # MULTIPLE_CHOICE only:
    options = models.JSONField(
        null=True,
        blank=True,
        help_text='Multiple-choice only: list of exactly 4 non-empty strings.',
    )
    correct_index = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(3)],
    )
    explanation = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quiz_questions',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'quiz_questions'
        ordering = ['-created_at']

    def __str__(self):
        return self.text[:60]

    def clean(self):
        super().clean()
        if self.question_type == self.QuestionType.TRUE_FALSE:
            if self.answer is None:
                raise ValidationError(
                    {'answer': 'Required for True/False questions.'},
                )
            if self.options is not None:
                raise ValidationError(
                    {'options': 'Must be null for True/False questions.'},
                )
            if self.correct_index is not None:
                raise ValidationError(
                    {'correct_index': 'Must be null for True/False questions.'},
                )
        elif self.question_type == self.QuestionType.MULTIPLE_CHOICE:
            if not isinstance(self.options, list) or len(self.options) != 4:
                raise ValidationError(
                    {'options': 'Must be a list of 4 items.'},
                )
            for i, opt in enumerate(self.options):
                if not isinstance(opt, str) or not opt.strip():
                    raise ValidationError(
                        {'options': f'Option {i} must be a non-empty string.'},
                    )
            if self.correct_index not in (0, 1, 2, 3):
                raise ValidationError(
                    {'correct_index': 'Must be one of 0, 1, 2, 3.'},
                )
            if self.answer is not None:
                raise ValidationError(
                    {'answer': 'Must be null for multiple-choice questions.'},
                )


class DailyQuiz(models.Model):
    """The row that records a calendar date on which the quiz was played.

    Created lazily on the first student's ``/today/start/`` of the day --
    no manager curation is required. Per-student question selection lives
    on :class:`AttemptQuestion`, not on this row.
    """

    date = models.DateField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_quizzes'
        ordering = ['-date']

    def __str__(self):
        return f'DailyQuiz {self.date}'


class QuizAttempt(models.Model):
    """A student's once-per-day session row.

    Created at ``/today/start/`` and immediately locked by the unique
    constraint on ``(user, daily_quiz)``, so leaving the app does not grant
    a retry. Status transitions are linear:
    ``IN_PROGRESS -> {SUBMITTED, FORFEITED, EXPIRED}``.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'In progress'
        SUBMITTED = 'submitted', 'Submitted'
        FORFEITED = 'forfeited', 'Forfeited'
        EXPIRED = 'expired', 'Expired'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quiz_attempts',
    )
    daily_quiz = models.ForeignKey(
        DailyQuiz,
        on_delete=models.CASCADE,
        related_name='attempts',
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    correct_count = models.PositiveSmallIntegerField(default=0)
    points_awarded = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    forfeit_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = 'quiz_attempts'
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'daily_quiz'],
                name='unique_quiz_attempt',
            ),
        ]

    def __str__(self):
        return f'{self.user} -> {self.daily_quiz} ({self.status})'


class AttemptQuestion(models.Model):
    """Through table -- pins a :class:`Question` to a slot on an attempt.

    The server picks 3 random questions per student per day and
    writes one row here for each ``position`` (1..3). The submit endpoint
    validates the answer set against ``attempt.served_questions``.
    """

    attempt = models.ForeignKey(
        QuizAttempt,
        on_delete=models.CASCADE,
        related_name='served_questions',
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name='attempt_servings',
    )
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)],
    )

    class Meta:
        db_table = 'attempt_questions'
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'position'],
                name='unique_attempt_position',
            ),
            models.UniqueConstraint(
                fields=['attempt', 'question'],
                name='unique_attempt_question_served',
            ),
        ]

    def __str__(self):
        return f'{self.attempt} #{self.position}'


class QuizAnswer(models.Model):
    """One submitted answer in a :class:`QuizAttempt`.

    Three rows per submitted attempt -- one per question that was actually
    served. ``selected_index`` is filled for MC, ``selected_bool`` for T/F.
    ``is_correct`` is computed server-side at submit time.
    """

    attempt = models.ForeignKey(
        QuizAttempt,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name='quiz_answers',
    )
    selected_index = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(3)],
    )
    selected_bool = models.BooleanField(null=True, blank=True)
    is_correct = models.BooleanField()

    class Meta:
        db_table = 'quiz_answers'
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'question'],
                name='unique_attempt_question',
            ),
        ]

    def __str__(self):
        return f'{self.attempt} Q{self.question_id}'
