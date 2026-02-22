from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from .exceptions import (
    InsufficientStarsError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
    EventFullError,
    DuplicateRequestError,
)

DOMAIN_EXCEPTION_MAP = {
    InsufficientStarsError: status.HTTP_400_BAD_REQUEST,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
    InvalidVerificationCodeError: status.HTTP_400_BAD_REQUEST,
    EventFullError: status.HTTP_409_CONFLICT,
    DuplicateRequestError: status.HTTP_409_CONFLICT,
}

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response

    for exc_class, status_code in DOMAIN_EXCEPTION_MAP.items():
        if isinstance(exc, exc_class):
            return Response(
                {'error': str(exc), 'error_code': exc.__class__.__name__},
                status=status_code,
            )

    return None