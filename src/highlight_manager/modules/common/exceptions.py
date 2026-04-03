from __future__ import annotations


class HighlightManagerError(Exception):
    """Base error for user-safe failures."""


class ValidationError(HighlightManagerError):
    """Raised when a user action is invalid for the current state."""


class StateTransitionError(HighlightManagerError):
    """Raised when an entity cannot move into the requested state."""


class NotFoundError(HighlightManagerError):
    """Raised when a requested entity does not exist."""
