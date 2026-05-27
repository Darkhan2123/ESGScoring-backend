class DomainException(Exception):
    pass

class InsufficientPointsError(DomainException):
    pass

class InvalidStateTransitionError(DomainException):
    pass

class InvalidVerificationCodeError(DomainException):
    pass

class EventFullError(DomainException):
    pass

class DuplicateRequestError(DomainException):
    pass

class ShopInactiveError(DomainException):
    pass


class NoQuizScheduledError(DomainException):
    pass


class AlreadySubmittedError(DomainException):
    pass


class InvalidQuizPayloadError(DomainException):
    """Domain error for malformed quiz input.

    ``errors`` optionally carries a per-row breakdown for bulk endpoints:
    ``[{"index": 5, "field": "options", "detail": "..."}, ...]``.
    """

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors


class TimeLimitExceededError(DomainException):
    pass