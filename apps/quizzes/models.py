"""
Models for the daily ESG quiz mini-game.

Five tables back the feature:

* :class:`Question` — the pool curators draw from.
* :class:`DailyQuiz` — one published quiz per calendar date.
* :class:`DailyQuizQuestion` — through table that pins three questions to a
  daily quiz in a fixed order (positions 1..3).
* :class:`QuizAttempt` — a student's once-per-day session row. Created at
  ``/today/start/`` so backgrounding the app cannot earn a retry; locked at
  the DB level via a unique ``(user, daily_quiz)`` constraint.
* :class:`QuizAnswer` — the chosen index for each of the three questions in
  a submitted attempt; ``is_correct`` is server-computed.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Question(models.Model):
    """A multiple-choice ESG question with exactly four options."""

    text = models.TextField()
    options = models.JSONField(
        help_text='List of exactly 4 non-empty option strings.',
    )
    correct_index = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(3)],
    )
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
        if not isinstance(self.options, list) or len(self.options) != 4:
            raise ValidationError({'options': 'Must be a list of 4 items.'})
        for i, opt in enumerate(self.options):
            if not isinstance(opt, str) or not opt.strip():
                raise ValidationError(
                    {'options': f'Option {i} must be a non-empty string.'},
                )
        if self.correct_index not in (0, 1, 2, 3):
            raise ValidationError(
                {'correct_index': 'Must be one of 0, 1, 2, 3.'},
            )


class DailyQuiz(models.Model):
    """The published quiz for a single calendar date.

    Pairs to three :class:`Question` rows through :class:`DailyQuizQuestion`,
    with ``position`` 1..3 fixing the order students see them in.
    """

    date = models.DateField(unique=True)
    created_by = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='daily_quizzes',
    )
    is_published = models.BooleanField(default=True)
    questions = models.ManyToManyField(
        Question,
        through='DailyQuizQuestion',
        related_name='daily_quizzes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_quizzes'
        ordering = ['-date']

    def __str__(self):
        return f'DailyQuiz {self.date}'


class DailyQuizQuestion(models.Model):
    """Through table — pins a :class:`Question` to a :class:`DailyQuiz` slot."""

    daily_quiz = models.ForeignKey(
        DailyQuiz,
        on_delete=models.CASCADE,
        related_name='quiz_questions',
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name='daily_quiz_links',
    )
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)],
    )

    class Meta:
        db_table = 'daily_quiz_questions'
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['daily_quiz', 'position'],
                name='unique_dailyquiz_position',
            ),
            models.UniqueConstraint(
                fields=['daily_quiz', 'question'],
                name='unique_dailyquiz_question',
            ),
        ]

    def __str__(self):
        return f'{self.daily_quiz} #{self.position}'


class QuizAttempt(models.Model):
    """A student's once-per-day session row.

    Created at ``/today/start/`` and immediately locked by the unique
    constraint on ``(user, daily_quiz)``, so leaving the app does not grant
    a retry. Status transitions are linear:
    ``IN_PROGRESS → {SUBMITTED, FORFEITED, EXPIRED}``.
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
        return f'{self.user} → {self.daily_quiz} ({self.status})'


class QuizAnswer(models.Model):
    """One submitted answer in a :class:`QuizAttempt`.

    Three rows per submitted attempt — one per question on that day's quiz.
    ``is_correct`` is computed server-side at submit time; the client only
    ever provides ``selected_index``.
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
        validators=[MinValueValidator(0), MaxValueValidator(3)],
    )
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
        return f'{self.attempt} Q{self.question_id}={self.selected_index}'
