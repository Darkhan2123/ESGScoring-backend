from django.db import IntegrityError
from rest_framework.views import exception_handler
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status
from .exceptions import (
    AlreadySubmittedError,
    DuplicateRequestError,
    EventFullError,
    InsufficientPointsError,
    InvalidQuizPayloadError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
    NoQuizScheduledError,
    PoolExhaustedError,
    ShopInactiveError,
    TimeLimitExceededError,
)

DOMAIN_EXCEPTION_MAP = {
    InsufficientPointsError: status.HTTP_400_BAD_REQUEST,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
    InvalidVerificationCodeError: status.HTTP_400_BAD_REQUEST,
    EventFullError: status.HTTP_409_CONFLICT,
    DuplicateRequestError: status.HTTP_409_CONFLICT,
    ShopInactiveError: status.HTTP_400_BAD_REQUEST,
    NoQuizScheduledError: status.HTTP_400_BAD_REQUEST,
    AlreadySubmittedError: status.HTTP_409_CONFLICT,
    InvalidQuizPayloadError: status.HTTP_400_BAD_REQUEST,
    TimeLimitExceededError: status.HTTP_409_CONFLICT,
    PoolExhaustedError: status.HTTP_400_BAD_REQUEST,
}


def _flatten_errors(detail):
    """
    Extract a single human-readable message from DRF error detail.
    DRF errors can be a dict, list, or string.
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        for item in detail:
            msg = _flatten_errors(item)
            if msg:
                return msg
        return str(detail[0]) if detail else "Validation error."
    if isinstance(detail, dict):
        # Prefer non_field_errors first (e.g. "Invalid email or password.")
        if 'non_field_errors' in detail:
            return _flatten_errors(detail['non_field_errors'])
        # Otherwise take the first field error
        for field, messages in detail.items():
            return _flatten_errors(messages)
    return "Validation error."


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    # Reformat DRF ValidationError into a consistent body for Android
    if response is not None and isinstance(exc, ValidationError):
        detail = response.data
        return Response(
            {
                'error': _flatten_errors(detail),
                'error_code': 'VALIDATION_ERROR',
                'errors': detail,   # full per-field breakdown
            },
            status=response.status_code,
        )

    if response is not None:
        return response

    for exc_class, status_code in DOMAIN_EXCEPTION_MAP.items():
        if isinstance(exc, exc_class):
            body = {'error': str(exc), 'error_code': exc.__class__.__name__}
            extra_errors = getattr(exc, 'errors', None)
            if extra_errors is not None:
                body['errors'] = extra_errors
            return Response(body, status=status_code)

    if isinstance(exc, IntegrityError):
        return Response(
            {
                'error': 'A database conflict occurred. Please check your data for duplicates.',
                'error_code': 'INTEGRITY_ERROR',
            },
            status=status.HTTP_409_CONFLICT,
        )

    return None