class HighlightError(Exception):
    """Base application exception."""


class UserFacingError(HighlightError):
    """Safe to display to Discord users."""


class ConfigurationError(HighlightError):
    """Raised when required guild configuration is missing."""


class StateTransitionError(UserFacingError):
    """Raised for invalid match state transitions."""
