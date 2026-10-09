"""Errors raised by use cases. Driving adapters map them to exit codes / HTTP statuses."""


class ApplicationError(Exception):
    """Base class for use-case errors."""


class NotFoundError(ApplicationError):
    """A referenced search, run, offer or link does not exist."""


class ConflictError(ApplicationError):
    """The request conflicts with existing state (e.g. a search name is taken)."""


class InvalidRequestError(ApplicationError):
    """The request is well-formed but not acceptable (unknown source/category/attribute)."""
