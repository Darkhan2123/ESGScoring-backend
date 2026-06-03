"""
Use-case layer for the daily ESG quiz (v2).

Differences from v1:
  * No manual daily curation. ``DailyQuiz`` rows are created lazily by
    ``start_daily_quiz`` on the first student call of the day.
  * Questions are picked per-student at start time, drawn uniformly at
    random from the active question pool (repeats across days allowed).
  * Each attempt owns its 3 served questions via :class:`AttemptQuestion`,
    so two students playing on the same day get independently-randomised
    question sets (and the submit endpoint validates against the attempt's
    served set, not against a shared DailyQuiz pin).
  * Questions come in two shapes (True/False and Multiple-choice); the
    bulk upload accepts both and the per-row validator infers the shape
    from the row's keys.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import (
    AlreadySubmittedError,
    InvalidQuizPayloadError,
    NoQuizScheduledError,
    PoolExhaustedError,
    TimeLimitExceededError,
)
from apps.users.models import User

from .models import (
    AttemptQuestion,
    DailyQuiz,
    Question,
    QuizAnswer,
    QuizAttempt,
)


SUBMIT_BASE_POINTS = 15
POINTS_PER_CORRECT = 5
QUESTIONS_PER_QUIZ = 3


# --- Helpers ---------------------------------------------------------------


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
    catalogue (``organization=None`` means "no scope restriction"). Raises
    :class:`InvalidQuizPayloadError` for org-role users with no organization.
    """
    if user.role == User.Role.ADMIN:
        return None
    try:
        return user.organization
    except Exception:  # noqa: BLE001 -- OneToOne reverse raises DoesNotExist
        raise InvalidQuizPayloadError(
            'You do not have an organization assigned.',
        )


# --- Question pool (manager) -----------------------------------------------


_TF = Question.QuestionType.TRUE_FALSE
_MC = Question.QuestionType.MULTIPLE_CHOICE


def _validate_question_item(item: dict, index: int) -> tuple[list[dict], str | None]:
    """Validate one bulk-upload row.

    Returns ``(errors, question_type)``. The shape is inferred from the
    presence of ``answer`` (T/F) or ``options`` (MC).
    """
    errors: list[dict] = []

    text = item.get('text')
    if not isinstance(text, str) or not text.strip():
        errors.append({
            'index': index, 'field': 'text',
            'detail': 'Must be a non-empty string.',
        })

    explanation = item.get('explanation', '')
    if explanation is not None and not isinstance(explanation, str):
        errors.append({
            'index': index, 'field': 'explanation',
            'detail': 'Must be a string.',
        })

    has_answer = 'answer' in item
    has_options = 'options' in item or 'correct_index' in item

    if has_answer and has_options:
        errors.append({
            'index': index, 'field': 'shape',
            'detail': 'Provide either {answer} (True/False) or {options + correct_index} (MC), not both.',
        })
        return errors, None
    if not has_answer and not has_options:
        errors.append({
            'index': index, 'field': 'shape',
            'detail': 'Provide either "answer" (True/False) or "options" + "correct_index" (MC).',
        })
        return errors, None

    if has_answer:
        if not isinstance(item.get('answer'), bool):
            errors.append({
                'index': index, 'field': 'answer',
                'detail': 'Must be true or false.',
            })
        return errors, _TF

    # has_options
    options = item.get('options')
    if not isinstance(options, list) or len(options) != 4:
        errors.append({
            'index': index, 'field': 'options',
            'detail': 'Must be a list of 4 strings.',
        })
    else:
        for i, opt in enumerate(options):
            if not isinstance(opt, str) or not opt.strip():
                errors.append({
                    'index': index, 'field': f'options[{i}]',
                    'detail': 'Must be a non-empty string.',
                })

    ci = item.get('correct_index')
    if not isinstance(ci, int) or ci not in (0, 1, 2, 3):
        errors.append({
            'index': index, 'field': 'correct_index',
            'detail': 'Must be one of 0, 1, 2, 3.',
        })

    return errors, _MC


@transaction.atomic
def bulk_create_questions(*, user: User, items: list[dict]) -> tuple[int, list[int]]:
    """Create many :class:`Question` rows atomically.

    Accepts a mix of True/False and Multiple-choice rows. Raises
    :class:`InvalidQuizPayloadError` with a per-row ``errors`` list if any
    row fails validation; no rows are inserted in that case.
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
    typed_items: list[tuple[dict, str]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            all_errors.append({
                'index': i, 'field': 'row',
                'detail': 'Each row must be a JSON object.',
            })
            continue
        row_errors, qtype = _validate_question_item(item, i)
        all_errors.extend(row_errors)
        if qtype is not None and not row_errors:
            typed_items.append((item, qtype))

    if all_errors:
        raise InvalidQuizPayloadError(
            'Some questions failed validation.', errors=all_errors,
        )

    rows: list[Question] = []
    for item, qtype in typed_items:
        explanation = (item.get('explanation') or '').strip()
        if qtype == _TF:
            rows.append(Question(
                text=item['text'].strip(),
                question_type=_TF,
                answer=bool(item['answer']),
                options=None,
                correct_index=None,
                explanation=explanation,
                created_by=organization,
            ))
        else:  # MC
            rows.append(Question(
                text=item['text'].strip(),
                question_type=_MC,
                answer=None,
                options=[opt.strip() for opt in item['options']],
                correct_index=item['correct_index'],
                explanation=explanation,
                created_by=organization,
            ))

    created = Question.objects.bulk_create(rows)
    return len(created), [q.pk for q in created]


# --- Pool scoping ----------------------------------------------------------


def question_pool_for_manager(user: User):
    """Curation-side scope: org users see their own pool, admins see all."""
    qs = Question.objects.all()
    if user.role == User.Role.ADMIN:
        return qs
    organization = _resolve_organization(user)
    return qs.filter(created_by=organization)


def _active_pool_ids() -> list[int]:
    """Return ids of all active questions available to draw from.

    Selection is drawn uniformly at random from this pool; a student may be
    served a question they have seen on a previous day (repeats allowed).
    """
    return list(
        Question.objects
        .filter(is_active=True)
        .values_list('pk', flat=True)
    )


# --- Attempt lifecycle -----------------------------------------------------


def _get_or_create_today_quiz_locked() -> DailyQuiz:
    """Return today's :class:`DailyQuiz`, creating it if missing.

    Called from inside ``start_daily_quiz``'s atomic block; the unique
    constraint on ``date`` makes the race safe even without a row-level
    lock on the table.
    """
    today = local_today()
    quiz, _ = DailyQuiz.objects.get_or_create(date=today)
    return quiz


def get_today_status_for_student(user: User) -> dict:
    """Read-only payload for ``/today/``.

    ``available`` means the student can start or resume right now:
      * not started yet and the pool has >= 3 active questions, or
      * an in-progress attempt that has not passed its deadline.
    A terminal attempt (submitted/forfeited/expired) -- or an in-progress one
    whose ``deadline_at`` has already passed -- reports ``available = False``
    with ``reason = "already_played"``. The deadline check is computed here
    only; the row is persisted as ``expired`` later by ``start``/``answer``
    (this endpoint stays read-only).
    """
    today = local_today()
    quiz = DailyQuiz.objects.filter(date=today).first()
    attempt = None
    if quiz is not None:
        attempt = QuizAttempt.objects.filter(user=user, daily_quiz=quiz).first()

    if attempt is not None:
        now = timezone.now()
        effectively_expired = (
            attempt.status == QuizAttempt.Status.IN_PROGRESS
            and now > attempt.deadline_at
        )
        if effectively_expired:
            attempt_status = QuizAttempt.Status.EXPIRED
        else:
            attempt_status = attempt.status

        playable = (
            attempt.status == QuizAttempt.Status.IN_PROGRESS
            and not effectively_expired
        )
        return {
            'available': playable,
            'daily_quiz_id': quiz.pk,
            'date': today.isoformat(),
            'attempt': attempt,
            'attempt_status': attempt_status,
            'reason': None if playable else 'already_played',
        }

    pool_count = Question.objects.filter(is_active=True).count()
    if pool_count < QUESTIONS_PER_QUIZ:
        return {
            'available': False,
            'daily_quiz_id': None,
            'date': today.isoformat(),
            'attempt': None,
            'attempt_status': 'not_started',
            'reason': 'pool_exhausted',
        }

    return {
        'available': True,
        'daily_quiz_id': quiz.pk if quiz else None,
        'date': today.isoformat(),
        'attempt': None,
        'attempt_status': 'not_started',
        'reason': None,
    }


def start_daily_quiz(
    *, user: User,
) -> tuple[QuizAttempt, DailyQuiz, list[AttemptQuestion], datetime]:
    """Create-or-resume today's attempt for ``user``.

    Creating a fresh attempt immediately grants ``SUBMIT_BASE_POINTS`` (the
    base reward for starting); resuming an in-progress attempt does not
    re-award it. Correct answers add points later in ``answer_question``.

    Returns ``(attempt, daily_quiz, served_questions, server_now)``.

    Raises:
        AlreadySubmittedError: the day is locked (submitted, forfeited, or
            already-expired attempt exists).
        PoolExhaustedError: the active question pool has fewer than 3
            questions in total.
    """
    deferred_error: Exception | None = None
    attempt: QuizAttempt | None = None
    server_now = timezone.now()

    with transaction.atomic():
        quiz = _get_or_create_today_quiz_locked()

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
            else:  # IN_PROGRESS
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
            pool_ids = _active_pool_ids()
            if len(pool_ids) < QUESTIONS_PER_QUIZ:
                deferred_error = PoolExhaustedError(
                    'Not enough questions available right now.',
                )
            else:
                picks = random.sample(pool_ids, QUESTIONS_PER_QUIZ)
                now = timezone.now()
                attempt = QuizAttempt.objects.create(
                    user=user,
                    daily_quiz=quiz,
                    status=QuizAttempt.Status.IN_PROGRESS,
                    deadline_at=now + timedelta(seconds=_time_limit_seconds()),
                    points_awarded=SUBMIT_BASE_POINTS,
                )
                AttemptQuestion.objects.bulk_create([
                    AttemptQuestion(
                        attempt=attempt,
                        question_id=pid,
                        position=i + 1,
                    )
                    for i, pid in enumerate(picks)
                ])
                # Base points are granted the moment the quiz starts; correct
                # answers add POINTS_PER_CORRECT each as they come in.
                User.objects.filter(pk=user.pk).update(
                    points=F('points') + SUBMIT_BASE_POINTS,
                )
                server_now = now

    if deferred_error is not None:
        raise deferred_error

    served = list(
        AttemptQuestion.objects
        .filter(attempt=attempt)
        .select_related('question')
        .order_by('position')
    )
    return attempt, attempt.daily_quiz, served, server_now


def answer_question(
    *, user: User, question_id: int,
    selected_index: int | None = None,
    selected_bool: bool | None = None,
    attempt_id: int | None = None,
) -> dict:
    """Record one answer, reveal its result, and finalize on the 3rd.

    Questions must be answered in served order (position 1, then 2, then 3).
    Each call stores one :class:`QuizAnswer` and returns whether it was
    correct plus the explanation. A correct answer credits
    ``POINTS_PER_CORRECT`` immediately (the ``SUBMIT_BASE_POINTS`` base was
    granted at start); the 3rd answer just locks the attempt as submitted.

    Returns a dict with the saved ``answer`` plus progress fields and the
    running ``correct_count`` / ``points_awarded`` for the attempt.

    Raises:
        NoQuizScheduledError: no quiz today, or the student never started one.
        AlreadySubmittedError: this attempt is already terminal.
        TimeLimitExceededError: ``deadline_at`` has passed.
        InvalidQuizPayloadError: wrong/out-of-order question, or the answer
            shape mismatches the question type.
    """
    today = local_today()
    quiz = DailyQuiz.objects.filter(date=today).first()
    if quiz is None:
        raise NoQuizScheduledError(
            'Start the quiz before submitting answers.',
        )

    deferred_error: Exception | None = None
    result: dict | None = None

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
                served = list(
                    attempt.served_questions
                    .select_related('question')
                    .order_by('position')
                )
                answered_count = attempt.answers.count()
                # Strict order: the next unanswered slot is the only one we accept.
                expected = served[answered_count]

                if question_id != expected.question_id:
                    deferred_error = InvalidQuizPayloadError(
                        'Answer the questions in order.',
                    )
                else:
                    q = expected.question
                    if q.question_type == _TF and selected_bool is not None:
                        is_correct = (selected_bool == q.answer)
                        answer = QuizAnswer.objects.create(
                            attempt=attempt, question=q,
                            selected_index=None, selected_bool=selected_bool,
                            is_correct=is_correct,
                        )
                    elif q.question_type == _MC and selected_index is not None:
                        is_correct = (selected_index == q.correct_index)
                        answer = QuizAnswer.objects.create(
                            attempt=attempt, question=q,
                            selected_index=selected_index, selected_bool=None,
                            is_correct=is_correct,
                        )
                    else:
                        deferred_error = InvalidQuizPayloadError(
                            'Answer shape does not match the question type.',
                        )

                    if deferred_error is None:
                        # A correct answer credits POINTS_PER_CORRECT right away
                        # (the base SUBMIT_BASE_POINTS was already granted at
                        # start). Points are never reverted, so leaving the quiz
                        # keeps whatever was earned so far.
                        if is_correct:
                            attempt.correct_count += 1
                            attempt.points_awarded += POINTS_PER_CORRECT
                            User.objects.filter(pk=user.pk).update(
                                points=F('points') + POINTS_PER_CORRECT,
                            )

                        new_count = answered_count + 1
                        is_complete = new_count == QUESTIONS_PER_QUIZ
                        update_fields = ['correct_count', 'points_awarded']
                        if is_complete:
                            attempt.status = QuizAttempt.Status.SUBMITTED
                            attempt.submitted_at = now
                            update_fields += ['status', 'submitted_at']
                        attempt.save(update_fields=update_fields)

                        result = {
                            'answer': answer,
                            'position': expected.position,
                            'answered_count': new_count,
                            'total_questions': QUESTIONS_PER_QUIZ,
                            'is_complete': is_complete,
                            'correct_count': attempt.correct_count,
                            'points_awarded': attempt.points_awarded,
                        }

    if deferred_error is not None:
        raise deferred_error
    return result  # type: ignore[return-value]


@transaction.atomic
def forfeit_daily_quiz(*, user: User, reason: str = 'app_background') -> QuizAttempt | None:
    """Lock today's in-progress attempt at 0 points; idempotent."""
    today = local_today()
    quiz = DailyQuiz.objects.filter(date=today).first()
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


def attempt_status_value(attempt: QuizAttempt | None) -> str:
    """Map an attempt row to the public ``attempt_status`` string."""
    if attempt is None:
        return 'not_started'
    return attempt.status
