class UserFacingError(Exception):
    """An error whose message is written for the person using the app.

    `str(exc)` is shown on screen verbatim, so the message must read well on a
    phone: no environment variables, no CLI flags, no library names, no raw
    stderr. Everything an operator needs goes in `log_detail`, which
    `ProcessRunUseCase` writes to the log and never stores on the run.

    The split exists because these two audiences used to share one string.
    Messages were written when the backend ran on the author's laptop, where
    the reader *was* the operator; once it was deployed, "Configure
    YTDLP_COOKIES_FILE on the server" started reaching people holding a phone,
    and yt-dlp's and FFmpeg's raw stderr went with it.
    """

    def __init__(self, message: str, *, log_detail: str | None = None) -> None:
        super().__init__(message)
        self.log_detail = log_detail


class MediaValidationError(UserFacingError):
    """The provided media (file or URL) failed validation or processing."""


class AnalysisUnavailableError(UserFacingError):
    """Gemini could not serve the request for a reason that is not the
    caller's fault and may well pass: the model is overloaded (503), the
    account is being rate limited (429), or the server erred (5xx).

    Separate from `MediaValidationError` because the honest advice is the
    opposite. Nothing is wrong with the media, so re-picking it is wasted
    work; the same request may succeed shortly.
    """


class GeminiConfigurationError(UserFacingError):
    """Gemini could not be reached because the client is not configured.

    A deployment fault, not a caller fault — so the caller is told only that
    analysis is unavailable, and the missing setting is named in the log.
    """


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
