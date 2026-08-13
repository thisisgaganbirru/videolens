class MediaValidationError(Exception):
    """The provided media (file or URL) failed validation or processing."""


class GeminiConfigurationError(RuntimeError):
    """Gemini could not be reached because the client is not configured."""


class TermsNotAcceptedError(Exception):
    """The caller did not accept the media-use terms."""


class InvalidSourceError(Exception):
    """The caller did not provide exactly one media source."""


class QuotaExceededError(Exception):
    """The shared daily analysis budget has been exhausted."""


class RunSchedulingError(Exception):
    """The run could not be queued for analysis after being accepted."""


class RunNotFoundError(Exception):
    """No run exists for the given id and owner."""
