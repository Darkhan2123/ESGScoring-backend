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