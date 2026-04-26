"""
Use-case layer for the ``events`` app.

Views in :mod:`apps.events.views` stay thin — they parse HTTP input, call one
of the functions below, and render the result. Every operation that involves
multi-entity writes, points accounting, or state transitions lives here so the
same logic can be reused from Django admin actions, management commands, or
future async workers without drift.
"""
from __future__ import annotations

import hmac

from django.db import transaction
from django.db.models import F

from apps.core.exceptions import (
    DuplicateRequestError,
    EventFullError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
)
from apps.users.models import User

from .models import Task, TaskParticipation


@transaction.atomic
def request_participation(*, user: User, task: Task) -> TaskParticipation:
    """Create a pending ``TaskParticipation`` for ``user`` on ``task``.

    Capacity and duplicate-request checks are performed here so a single
    request race cannot produce two ``PENDING`` rows or push the approved
    count past ``max_participants``.

    Raises:
        EventFullError: the task is already at capacity.
        DuplicateRequestError: the user has already applied to this task.
    """
    if task.is_full:
        raise EventFullError(
            'This task has reached the maximum number of participants.'
        )

    participation, created = TaskParticipation.objects.get_or_create(
        task=task,
        student=user,
        defaults={'status': TaskParticipation.Status.PENDING},
    )
    if not created:
        raise DuplicateRequestError('You have already applied to this task.')
    return participation


@transaction.atomic
def decide_participation(
    *, participation: TaskParticipation, new_status: str,
) -> TaskParticipation:
    """Move ``participation`` to ``APPROVED`` or ``REJECTED``.

    Validates the state transition and re-checks capacity on approval so a
    burst of approvals cannot exceed ``task.max_participants``.

    Raises:
        InvalidStateTransitionError: transition not allowed from current state.
        EventFullError: task is full and ``new_status`` is ``APPROVED``.
    """
    locked = (
        TaskParticipation.objects
        .select_for_update()
        .select_related('task')
        .get(pk=participation.pk)
    )
    if not locked.can_transition_to(new_status):
        raise InvalidStateTransitionError(
            f"Cannot change status from '{locked.status}' to '{new_status}'."
        )
    if (
        new_status == TaskParticipation.Status.APPROVED
        and locked.task.is_full
    ):
        raise EventFullError(
            'This task has reached the maximum number of participants.'
        )
    locked.status = new_status
    locked.save(update_fields=['status', 'updated_at'])
    return locked


@transaction.atomic
def complete_participation(
    *, user: User, task: Task, code: str,
) -> TaskParticipation:
    """Credit ``task.points_reward`` to ``user`` after code verification.

    Uses :func:`hmac.compare_digest` to avoid a timing side-channel, then
    locks the participation row and increments the user's points with ``F()``
    so the DB handles concurrency correctly.

    Raises:
        InvalidVerificationCodeError: submitted code does not match.
        TaskParticipation.DoesNotExist: user has no approved participation.
    """
    if not hmac.compare_digest(task.verification_code, code):
        raise InvalidVerificationCodeError('Invalid verification code.')

    participation = (
        TaskParticipation.objects
        .select_for_update()
        .get(
            task=task,
            student=user,
            status=TaskParticipation.Status.APPROVED,
        )
    )
    participation.status = TaskParticipation.Status.COMPLETED
    participation.save(update_fields=['status', 'updated_at'])

    User.objects.filter(pk=user.pk).update(
        points=F('points') + task.points_reward,
    )
    return participation
