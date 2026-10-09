"""Domain error types."""


class DomainError(Exception):
    """Base class for every error raised by the domain."""


class InvalidValueError(DomainError, ValueError):
    """A value object or entity was constructed with an invalid value."""
