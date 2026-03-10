from rest_framework.views import exception_handler
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status
from .exceptions import (
    InsufficientPointsError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
    EventFullError,
    DuplicateRequestError,
)

DOMAIN_EXCEPTION_MAP = {
    InsufficientPointsError: status.HTTP_400_BAD_REQUEST,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
    InvalidVerificationCodeError: status.HTTP_400_BAD_REQUEST,
    EventFullError: status.HTTP_409_CONFLICT,
    DuplicateRequestError: status.HTTP_409_CONFLICT,
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
            return Response(
                {'error': str(exc), 'error_code': exc.__class__.__name__},
                status=status_code,
            )

    return None