class DomainException(Exception):
    pass

class InsufficientStarsError(DomainException):
    pass

class InvalidStateTransitionError(DomainException):
    pass

class InvalidVerificationCodeError(DomainException):
    pass

class EventFullError(DomainException):
    pass

class DuplicateRequestError(DomainException):
    pass