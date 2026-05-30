"""
Use-case layer for the ``projects`` app.

Projects have a deliberately light lifecycle: an organization publishes a
project (and gets a verification code), students are chosen externally via the
Google Form, and a chosen student claims ``points_reward`` once by submitting
the code. The single state-changing operation lives here so points accounting
stays atomic and reusable.
"""
from __future__ import annotations

import hmac

from django.db import transaction
from django.db.models import F

from apps.core.exceptions import (
    DuplicateRequestError,
    InvalidVerificationCodeError,
)
from apps.users.models import User

from .models import Project, ProjectCompletion


@transaction.atomic
def claim_project_points(
    *, user: User, project: Project, code: str,
) -> ProjectCompletion:
    """Credit ``project.points_reward`` to ``user`` after code verification.

    Uses :func:`hmac.compare_digest` to avoid a timing side-channel and a
    unique ``(project, student)`` row to guarantee a student can only claim a
    project's points once.

    Raises:
        InvalidVerificationCodeError: submitted code does not match.
        DuplicateRequestError: the user already claimed this project.
    """
    if not hmac.compare_digest(project.verification_code or '', code):
        raise InvalidVerificationCodeError('Invalid verification code.')

    completion, created = ProjectCompletion.objects.get_or_create(
        project=project, student=user,
    )
    if not created:
        raise DuplicateRequestError(
            'You have already claimed points for this project.'
        )

    User.objects.filter(pk=user.pk).update(
        points=F('points') + project.points_reward,
    )
    return completion
