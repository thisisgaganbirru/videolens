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
    """The shared daily analysis budget has been exhausted.

    `retry_after_seconds` is how long until the budget frees (the next UTC
    day); the API sends it as `Retry-After`. None when unknown.
    """

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RateLimitedError(Exception):
    """The caller has made too many requests in the current rate-limit window.

    `retry_after_seconds` is how long until the window frees a request; the
    API sends it as `Retry-After`, which the frontend turns into "Try again in
    about N minutes". None when the limiter could not say.
    """

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RunSchedulingError(Exception):
    """The run could not be queued for analysis after being accepted."""


class RunNotFoundError(Exception):
    """No run exists for the given id and owner."""


class DeviceTokenInvalidError(Exception):
    """A free run was requested without a valid signed device token. The
    client fetches a fresh one from `GET /api/free-runs` and retries."""


class FreeRunsExhaustedError(Exception):
    """This device (or its network) has used today's free runs, or, with
    `scope="account"`, this account has used today's (per UTC day since
    2026-11-14). `limit` and `used` are always the device's (or account's)
    own numbers, whichever counter tripped; `period` ("day") is the
    counter's period."""

    def __init__(self, message: str, *, limit: int, used: int, scope: str = "device", period: str = "day") -> None:
        super().__init__(message)
        self.limit = limit
        self.used = used
        self.scope = scope
        self.period = period


class AuthenticationError(Exception):
    """The credential presented could not be verified (401). The message is
    safe to show; it never echoes the credential."""


class ForbiddenError(Exception):
    """The caller is known but this credential may not do this (403): an API
    key asking to manage keys, or a workspace member who is not its owner."""


class AuthNotConfiguredError(RuntimeError):
    """A bearer token arrived but this deployment has no identity provider
    configured (503). Lives in the domain, not the JWT adapter, so the API
    layer maps it without importing an adapter: any `TokenVerifier` raises
    this one type."""


class AccountsNotConfiguredError(AuthNotConfiguredError):
    """A signed-in caller asked for something that needs the account
    directory (API keys), on a deployment that has none (503)."""


class ApiKeyLimitError(Exception):
    """The workspace already holds its maximum of live API keys (409)."""


class ApiKeyNotFoundError(Exception):
    """No live API key with that id in the caller's workspace (404)."""


class ClientIdInvalidError(Exception):
    """An anonymous caller sent no valid `X-Client-ID` (400, as before
    accounts existed: it is a malformed request, not a failed sign-in)."""


class AccountDeletionError(UserFacingError):
    """Deleting an account failed part-way (500). Whatever was already
    removed stays removed; the provider user goes last, so retrying with the
    same session finishes the job."""


LONG_RUN_IN_PROGRESS_MESSAGE = "You already have a long video processing. Wait for it to finish."


class LongRunInProgressError(UserFacingError):
    """This account already has a run above the standard limits queued or
    processing (429, `code: long_run_in_progress`). At most one at a time;
    standard-length runs are never refused for it. A user-facing error so a
    link run that only turns out long in the worker fails with the same
    sentence."""

    def __init__(self, message: str = LONG_RUN_IN_PROGRESS_MESSAGE, *, log_detail: str | None = None) -> None:
        super().__init__(message, log_detail=log_detail)


RUN_INTERRUPTED_MESSAGE = "Analysis was interrupted before it finished. Please try again."
BYOK_KEY_EXPIRED_MESSAGE = "This run waited too long to start. Please try again."


class OwnKeyUnavailableError(UserFacingError):
    """A run admitted on the caller's own Gemini key reached the worker with
    no key in the single-use vault. It is failed rather than run on the
    shared key, which it was never counted against (docs/backend/byok.md).

    `started`: an earlier attempt of the job already took the key (an arq
    retry after its worker died), so the person sees "interrupted" rather
    than "waited too long"."""

    def __init__(self, *, started: bool = False) -> None:
        super().__init__(
            RUN_INTERRUPTED_MESSAGE if started else BYOK_KEY_EXPIRED_MESSAGE,
            log_detail=(
                "admitted on the caller's own Gemini key, but the BYOK vault had no key ("
                + (
                    "an earlier attempt of this job took it; arq retry"
                    if started
                    else "the 15-minute vault entry expired while the job was queued"
                )
                + "); refused rather than use the shared GEMINI_API_KEY"
            ),
        )
        self.started = started


# ------------------------------------------------------------------ billing
# docs/backend/billing.md. Each carries a machine-readable `code` the API
# sends next to `detail`, because the client acts on it.


class BillingError(Exception):
    code = "billing_error"


class BillingNotConfiguredError(BillingError):
    """Billing is off on this deployment (a required STRIPE_* setting is
    blank, or there is no account store). 503 `billing_disabled`."""

    code = "billing_disabled"

    def __init__(self, message: str = "Subscriptions are not available on this server.") -> None:
        super().__init__(message)


class AlreadySubscribedError(BillingError):
    """The account already holds a live subscription (409)."""

    code = "already_subscribed"

    def __init__(self, message: str = "You already have a subscription. Manage it from Billing.") -> None:
        super().__init__(message)


class NoBillingAccountError(BillingError):
    """The account has never started a checkout, so there is no Stripe
    customer to open the portal for (404)."""

    code = "no_billing_account"

    def __init__(self, message: str = "There is no billing account for you yet.") -> None:
        super().__init__(message)


class BillingIntervalError(BillingError):
    """`interval` is not one this deployment sells (400): not "month" or
    "year", or "year" with no yearly price configured."""

    code = "invalid_interval"


class BillingProviderError(BillingError):
    """Stripe refused or could not be reached (503). The message is for the
    phone; the cause goes to the log only."""

    code = "billing_unavailable"

    def __init__(
        self, message: str = "Payments are unavailable right now. Try again in a moment.", *, log_detail: str | None = None
    ) -> None:
        super().__init__(message)
        self.log_detail = log_detail


class WebhookSignatureError(Exception):
    """A webhook whose `Stripe-Signature` does not verify (400). Nothing in
    it is read."""


class ExtraRunsCapReachedError(Exception):
    """A paid account reached `PAID_EXTRA_RUNS_MONTHLY_CAP` extra runs this
    UTC month (402 `extra_runs_cap`): a safety net against a runaway bill,
    not a price point."""

    def __init__(self, message: str, *, limit: int) -> None:
        super().__init__(message)
        self.limit = limit


SUBSCRIPTION_CANCEL_FAILED_MESSAGE = (
    "We couldn't cancel your subscription, so your account was not deleted. Please try again."
)


class SubscriptionCancelFailedError(AccountDeletionError):
    """Account deletion stopped before anything was removed: the account's
    Stripe subscription could not be cancelled, and deleting the rows would
    leave a subscription billing nobody we could still find (503
    `subscription_cancel_failed`)."""

    def __init__(self, *, log_detail: str | None = None) -> None:
        super().__init__(SUBSCRIPTION_CANCEL_FAILED_MESSAGE, log_detail=log_detail)


# ------------------------------------------------- deletion hold, saved history
# docs/backend/saved-history.md.


ACCOUNT_PENDING_DELETION_MESSAGE = (
    "This account was deleted. You can restore it until it is removed for good."
)


class AccountPendingDeletionError(Exception):
    """A signed-in person whose account is in the 30-day deletion hold (410
    `account_pending_deletion`, with `purge_at`). Every account-scoped
    endpoint answers this except `POST /api/me/restore`, so the client can
    offer "Restore your account?"."""

    def __init__(self, purge_at, message: str = ACCOUNT_PENDING_DELETION_MESSAGE) -> None:
        super().__init__(message)
        self.purge_at = purge_at


class AccountRestoreClosedError(Exception):
    """A restore asked for after the hold ended (410 `restore_window_closed`):
    the account is about to be, or already was, removed for good."""

    def __init__(self, message: str = "This account can no longer be restored.") -> None:
        super().__init__(message)


class SavedRunNotFoundError(Exception):
    """No saved run with that id for this account (404)."""


class InvalidCursorError(Exception):
    """A saved-history page cursor that does not decode (400)."""
