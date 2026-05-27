"""
Use-case layer for the daily ESG quiz.

Mirrors :mod:`apps.events.services` — views are thin, every mutation lives
here, and every entry point that touches points or the per-day attempt row
runs inside :func:`django.db.transaction.atomic` with
:meth:`~django.db.models.query.QuerySet.select_for_update` locks where
multiple callers could race.

Anti-cheat invariants:

* Exactly one :class:`~apps.quizzes.models.QuizAttempt` row per
  ``(user, daily_quiz)`` — enforced by the DB unique constraint and created
  on ``/today/start/`` so backgrounding the app cannot earn a retry.
* ``deadline_at`` is server-set; late submits flip the attempt to
  :attr:`~apps.quizzes.models.QuizAttempt.Status.EXPIRED`.
* Scoring is server-computed from ``correct_index``, which never leaves
  the server before the student locks their answers in.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import (
    AlreadySubmittedError,
    InvalidQuizPayloadError,
    NoQuizScheduledError,
    TimeLimitExceededError,
)
from apps.users.models import User

from .models import (
    DailyQuiz,
    DailyQuizQuestion,
    Question,
    QuizAnswer,
    QuizAttempt,
)


SUBMIT_BASE_POINTS = 15
POINTS_PER_CORRECT = 5


def local_today() -> date:
    """Return the current local date, honouring ``settings.TIME_ZONE``."""
    return timezone.localtime(timezone.now()).date()


def _time_limit_seconds() -> int:
    return int(getattr(settings, 'QUIZ_TIME_LIMIT_SECONDS', 120))


def _bulk_max_items() -> int:
    return int(getattr(settings, 'QUIZ_BULK_MAX_ITEMS', 200))


def _resolve_organization(user: User):
    """Return the user's organization or ``None`` for admins.

    Org users always operate inside their own pool; admins act on the whole
    catalogue (``organization=None`` means "no scope restriction").
    """
    if user.role == User.Role.ADMIN:
        return None
    try:
        return user.organization
    except Exception:  # noqa: BLE001 — OneToOne reverse raises DoesNotExist
        raise InvalidQuizPayloadError(
            'You do not have an organization assigned.',
        )


# ─── Question pool ─────────────────────────────────────────────────


def _validate_question_item(item: dict, index: int) -> list[dict]:
    """Return a list of per-row errors for a single bulk-upload row."""
    errors: list[dict] = []

    text = item.get('text')
    if not isinstance(text, str) or not text.strip():
        errors.append({'index': index, 'field': 'text', 'detail': 'Must be a non-empty string.'})

    options = item.get('options')
    if not isinstance(options, list) or len(options) != 4:
        errors.append({'index': index, 'field': 'options', 'detail': 'Must be a list of 4 strings.'})
    else:
        for i, opt in enumerate(options):
            if not isinstance(opt, str) or not opt.strip():
                errors.append({
                    'index': index,
                    'field': f'options[{i}]',
                    'detail': 'Must be a non-empty string.',
                })

    correct_index = item.get('correct_index')
    if not isinstance(correct_index, int) or correct_index not in (0, 1, 2, 3):
        errors.append({
            'index': index,
            'field': 'correct_index',
            'detail': 'Must be one of 0, 1, 2, 3.',
        })

    return errors


@transaction.atomic
def bulk_create_questions(*, user: User, items: list[dict]) -> tuple[int, list[int]]:
    """Create many :class:`Question` rows atomically.

    Raises :class:`InvalidQuizPayloadError` with a per-row ``errors`` list if
    any row fails validation; no rows are inserted in that case.
    """
    if not isinstance(items, list) or not items:
        raise InvalidQuizPayloadError('No questions provided.')

    cap = _bulk_max_items()
    if len(items) > cap:
        raise InvalidQuizPayloadError(
            f'Cannot create more than {cap} questions per request.',
        )

    organization = _resolve_organization(user)

    all_errors: list[dict] = []
    for i, item in enumerate(items):
        all_errors.extend(_validate_question_item(item, i))

    if all_errors:
        raise InvalidQuizPayloadError(
            'Some questions failed validation.', errors=all_errors,
        )

    rows = [
        Question(
            text=item['text'].strip(),
            options=[opt.strip() for opt in item['options']],
            correct_index=item['correct_index'],
            created_by=organization,
        )
        for item in items
    ]
    created = Question.objects.bulk_create(rows)
    return len(created), [q.pk for q in created]


def _question_pool_for(user: User):
    """Scope helper: org users see only their own pool, admins see all."""
    qs = Question.objects.all()
    if user.role == User.Role.ADMIN:
        return qs
    organization = _resolve_organization(user)
    return qs.filter(created_by=organization)


def _fetch_questions_for_quiz(*, user: User, question_ids: list[int]) -> list[Question]:
    """Return the 3 requested questions, in the supplied order.

    Raises :class:`InvalidQuizPayloadError` if any id is missing from the
    caller-scoped pool or inactive.
    """
    pool = _question_pool_for(user).filter(is_active=True, pk__in=question_ids)
    found = {q.pk: q for q in pool}
    missing = [qid for qid in question_ids if qid not in found]
    if missing:
        raise InvalidQuizPayloadError(
            f'Unknown or unavailable question ids: {missing}.',
        )
    return [found[qid] for qid in question_ids]


# ─── Daily quiz curation ───────────────────────────────────────────


@transaction.atomic
def create_daily_quiz(*, user: User, quiz_date: date, question_ids: list[int]) -> DailyQuiz:
    """Schedule the daily quiz for ``quiz_date`` with three ordered questions."""
    if len(question_ids) != 3 or len(set(question_ids)) != 3:
        raise InvalidQuizPayloadError(
            'Provide exactly three distinct question ids.',
        )

    questions = _fetch_questions_for_quiz(user=user, question_ids=question_ids)
    organization = _resolve_organization(user)

    quiz = DailyQuiz.objects.create(date=quiz_date, created_by=organization)
    DailyQuizQuestion.objects.bulk_create([
        DailyQuizQuestion(daily_quiz=quiz, question=q, position=i + 1)
        for i, q in enumerate(questions)
    ])
    return quiz


@transaction.atomic
def update_daily_quiz(
    *,
    user: User,
    quiz: DailyQuiz,
    is_published: bool | None = None,
    question_ids: list[int] | None = None,
) -> DailyQuiz:
    """Patch an existing daily quiz.

    Refused once a student has started an attempt — late edits would change
    what was already locked in.
    """
    if quiz.attempts.exists():
        raise AlreadySubmittedError(
            'Cannot edit a daily quiz once students have begun an attempt.',
        )

    changed = False
    if is_published is not None:
        quiz.is_published = is_published
        changed = True

    if question_ids is not None:
        if len(question_ids) != 3 or len(set(question_ids)) != 3:
            raise InvalidQuizPayloadError(
                'Provide exactly three distinct question ids.',
            )
        questions = _fetch_questions_for_quiz(user=user, question_ids=question_ids)
        quiz.quiz_questions.all().delete()
        DailyQuizQuestion.objects.bulk_create([
            DailyQuizQuestion(daily_quiz=quiz, question=q, position=i + 1)
            for i, q in enumerate(questions)
        ])
        changed = True

    if changed:
        quiz.save(update_fields=['is_published', 'updated_at'])
    return quiz


# ─── Attempt lifecycle ─────────────────────────────────────────────


def _get_today_quiz_locked() -> DailyQuiz | None:
    """Return today's published quiz (no lock — read-only helper)."""
    return (
        DailyQuiz.objects
        .filter(date=local_today(), is_published=True)
        .first()
    )


def get_today_quiz_for_student(user: User) -> tuple[DailyQuiz | None, QuizAttempt | None]:
    """Read-only status used by ``/today/`` — never creates an attempt."""
    quiz = (
        DailyQuiz.objects
        .filter(date=local_today(), is_published=True)
        .prefetch_related('quiz_questions__question')
        .first()
    )
    if quiz is None:
        return None, None
    attempt = (
        QuizAttempt.objects
        .filter(user=user, daily_quiz=quiz)
        .first()
    )
    return quiz, attempt


def ordered_questions(quiz: DailyQuiz) -> list[DailyQuizQuestion]:
    """Return the through rows for ``quiz`` ordered by ``position``.

    Returned objects expose ``question`` already loaded so the serializer
    can read text + options without N+1.
    """
    return list(
        quiz.quiz_questions.select_related('question').order_by('position'),
    )


def start_daily_quiz(
    *, user: User,
) -> tuple[QuizAttempt, DailyQuiz, list[DailyQuizQuestion], datetime]:
    """Create-or-resume today's attempt for ``user``.

    Returns ``(attempt, daily_quiz, ordered_questions, server_now)``.

    Raises:
        NoQuizScheduledError: nothing published for today.
        AlreadySubmittedError: the day is locked (submitted, forfeited, or
            expired).
    """
    quiz = _get_today_quiz_locked()
    if quiz is None:
        raise NoQuizScheduledError('No quiz is scheduled for today.')

    # The atomic block needs to *commit* an EXPIRED transition even when we
    # ultimately raise — so we record the intended exception, exit the block
    # cleanly (commit), and then raise outside it.
    deferred_error: Exception | None = None
    attempt: QuizAttempt | None = None
    server_now = timezone.now()

    with transaction.atomic():
        existing = (
            QuizAttempt.objects
            .select_for_update()
            .filter(user=user, daily_quiz=quiz)
            .first()
        )

        if existing is not None:
            if existing.status in (
                QuizAttempt.Status.SUBMITTED,
                QuizAttempt.Status.FORFEITED,
                QuizAttempt.Status.EXPIRED,
            ):
                deferred_error = AlreadySubmittedError(
                    'You have already played today.',
                )
            elif existing.status == QuizAttempt.Status.IN_PROGRESS:
                now = timezone.now()
                if now < existing.deadline_at:
                    attempt = existing
                    server_now = now
                else:
                    existing.status = QuizAttempt.Status.EXPIRED
                    existing.submitted_at = now
                    existing.save(update_fields=['status', 'submitted_at'])
                    deferred_error = AlreadySubmittedError(
                        'You have already played today.',
                    )
        else:
            now = timezone.now()
            attempt = QuizAttempt.objects.create(
                user=user,
                daily_quiz=quiz,
                status=QuizAttempt.Status.IN_PROGRESS,
                deadline_at=now + timedelta(seconds=_time_limit_seconds()),
            )
            server_now = now

    if deferred_error is not None:
        raise deferred_error

    return attempt, quiz, ordered_questions(quiz), server_now


def submit_daily_quiz(
    *, user: User, answers: list[dict], attempt_id: int | None = None,
) -> tuple[QuizAttempt, list[QuizAnswer], int]:
    """Score and lock the student's attempt for today.

    ``answers`` is ``[{question_id, selected_index}, ...]``. Server-side
    scoring guarantees the client cannot inflate points: only the chosen
    index is trusted.

    Raises:
        NoQuizScheduledError: no quiz today, or the student never started one.
        AlreadySubmittedError: this attempt is already terminal.
        TimeLimitExceededError: ``deadline_at`` has passed.
        InvalidQuizPayloadError: answers don't match today's question set.
    """
    quiz = _get_today_quiz_locked()
    if quiz is None:
        raise NoQuizScheduledError('No quiz is scheduled for today.')

    # Collect a deferred exception so the EXPIRED transition still commits
    # before we raise. We exit the atomic block normally on every path.
    deferred_error: Exception | None = None
    result: tuple[QuizAttempt, list[QuizAnswer], int] | None = None

    with transaction.atomic():
        attempt_qs = (
            QuizAttempt.objects
            .select_for_update()
            .filter(user=user, daily_quiz=quiz)
        )
        if attempt_id is not None:
            attempt_qs = attempt_qs.filter(pk=attempt_id)
        attempt = attempt_qs.first()

        if attempt is None:
            deferred_error = NoQuizScheduledError(
                'Start the quiz before submitting answers.',
            )
        elif attempt.status != QuizAttempt.Status.IN_PROGRESS:
            deferred_error = AlreadySubmittedError(
                'You have already played today.',
            )
        else:
            now = timezone.now()
            if now > attempt.deadline_at:
                attempt.status = QuizAttempt.Status.EXPIRED
                attempt.submitted_at = now
                attempt.save(update_fields=['status', 'submitted_at'])
                deferred_error = TimeLimitExceededError(
                    'Time limit exceeded. Attempt forfeited.',
                )
            else:
                today_question_ids = set(
                    quiz.quiz_questions.values_list('question_id', flat=True),
                )
                submitted_ids = [a['question_id'] for a in answers]
                if (
                    len(submitted_ids) != 3
                    or set(submitted_ids) != today_question_ids
                ):
                    deferred_error = InvalidQuizPayloadError(
                        "Answers must match exactly the 3 questions of today's quiz.",
                    )
                else:
                    questions = {
                        q.pk: q
                        for q in Question.objects.filter(pk__in=today_question_ids)
                    }
                    correct_count = 0
                    answer_rows: list[QuizAnswer] = []
                    for a in answers:
                        q = questions[a['question_id']]
                        is_correct = (a['selected_index'] == q.correct_index)
                        if is_correct:
                            correct_count += 1
                        answer_rows.append(QuizAnswer(
                            attempt=attempt,
                            question=q,
                            selected_index=a['selected_index'],
                            is_correct=is_correct,
                        ))

                    points_awarded = (
                        SUBMIT_BASE_POINTS + POINTS_PER_CORRECT * correct_count
                    )

                    QuizAnswer.objects.bulk_create(answer_rows)

                    attempt.status = QuizAttempt.Status.SUBMITTED
                    attempt.correct_count = correct_count
                    attempt.points_awarded = points_awarded
                    attempt.submitted_at = now
                    attempt.save(update_fields=[
                        'status', 'correct_count', 'points_awarded', 'submitted_at',
                    ])

                    User.objects.filter(pk=user.pk).update(
                        points=F('points') + points_awarded,
                    )

                    breakdown = list(
                        QuizAnswer.objects
                        .filter(attempt=attempt)
                        .select_related('question')
                        .order_by('question__id'),
                    )
                    result = (attempt, breakdown, points_awarded)

    if deferred_error is not None:
        raise deferred_error
    return result  # type: ignore[return-value]


@transaction.atomic
def forfeit_daily_quiz(*, user: User, reason: str = 'app_background') -> QuizAttempt | None:
    """Lock today's in-progress attempt at 0 points; idempotent."""
    quiz = _get_today_quiz_locked()
    if quiz is None:
        return None

    attempt = (
        QuizAttempt.objects
        .select_for_update()
        .filter(user=user, daily_quiz=quiz)
        .first()
    )
    if attempt is None:
        return None

    if attempt.status != QuizAttempt.Status.IN_PROGRESS:
        return attempt

    attempt.status = QuizAttempt.Status.FORFEITED
    attempt.forfeit_reason = (reason or 'app_background')[:32]
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=['status', 'forfeit_reason', 'submitted_at'])
    return attempt


# ─── Convenience for the views ────────────────────────────────────


def attempt_status_value(attempt: QuizAttempt | None) -> str:
    """Map an attempt row to the public ``attempt_status`` string."""
    if attempt is None:
        return 'not_started'
    return attempt.status
