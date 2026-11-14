import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..domain.entities import (
    AccountFreeRunClaim,
    BillingAccount,
    FreeRunClaim,
    FreeRunPeriod,
    FreeRunScope,
    Principal,
    Run,
)
from ..domain.entitlements import MediaLimits
from ..domain.errors import (
    DeviceTokenInvalidError,
    ExtraRunsCapReachedError,
    FreeRunsExhaustedError,
    InvalidSourceError,
    LongRunInProgressError,
    MediaValidationError,
    QuotaExceededError,
    RunSchedulingError,
    TermsNotAcceptedError,
)
from ..domain.policies import seconds_until_next_utc_day, utc_month
from ..domain.run_facts import file_platform
from ..domain.ports import (
    AccountFreeRunAllowance,
    DeviceTokenSigner,
    ExtraRunLedger,
    FreeRunAllowance,
    JobQueue,
    LongRunGuard,
    MediaProcessor,
    ObjectStore,
    RunRepository,
    SpendCap,
    UploadedFile,
)
from .billing import BillingPlans
from .entitlements import EntitlementResolver

FREE_RUNS_USED_MESSAGE = "You have used your free runs. Add your own Gemini key to keep going."
ACCOUNT_FREE_RUNS_USED_MESSAGE = (
    "You have used today's free runs. Add your own Gemini key to keep going, or come back tomorrow."
)
EXTRA_RUNS_CAP_MESSAGE = (
    "You have reached this month's limit on extra runs. Add your own Gemini key to keep going, "
    "or wait for next month."
)


@dataclass(frozen=True)
class _Admission:
    """The free run `_admit` took, and the allowance it came from (the
    device one or the account one), so the hold, the refund and the release
    go back to the same counter."""

    allowance: Any  # FreeRunAllowance | AccountFreeRunAllowance | _ExtraRunHold: same hold/refund/release shape
    claim: FreeRunClaim | AccountFreeRunClaim | None


class _ExtraRunHold:
    """A paid account's run past its included ones, as an "allowance" with
    the same hold/release/refund shape, so intake's failure path voids it
    exactly where it would hand a free run back. Nothing is counted: the
    ledger row is the extra run, billed only once the run completes."""

    def __init__(self, ledger: ExtraRunLedger, account: BillingAccount, period: str) -> None:
        self._ledger = ledger
        self._account = account
        self._period = period

    async def hold(self, run_id: str, claim: None) -> None:
        await self._ledger.hold(
            run_id,
            account_id=self._account.account_id,
            customer_id=self._account.stripe_customer_id,
            period=self._period,
        )

    async def release(self, run_id: str, *, refund: bool) -> bool:
        return await self._ledger.void(run_id)

    async def refund(self, claim: None) -> None:
        return None



class CreateRunUseCase:
    """Accepts a media source (file or URL), applies the intake business
    rules (terms accepted, exactly one source, free-run allowance, daily
    spend cap), and schedules the run for analysis.

    `distributed` mirrors the deployment topology (Redis queue + S3 present):
    in that mode an uploaded file is pushed to object storage and the local
    copy is deleted immediately, since the worker that processes it runs in
    a different process than the one that received the upload.
    """

    def __init__(
        self,
        *,
        runs: RunRepository,
        media: MediaProcessor,
        storage: ObjectStore,
        queue: JobQueue,
        spend_cap: SpendCap,
        free_runs: FreeRunAllowance,
        device_tokens: DeviceTokenSigner,
        distributed: bool,
        account_free_runs: AccountFreeRunAllowance | None = None,
        entitlements: EntitlementResolver | None = None,
        long_runs: LongRunGuard | None = None,
        billing: BillingPlans | None = None,
    ) -> None:
        self._runs = runs
        self._media = media
        self._storage = storage
        self._queue = queue
        self._spend_cap = spend_cap
        self._free_runs = free_runs
        self._device_tokens = device_tokens
        self._distributed = distributed
        # None (tests, older wiring) = no account allowance: everyone is on
        # the device rule, exactly as before it existed.
        self._account_free_runs = account_free_runs
        # None (tests, older wiring) = standard limits for everyone and no
        # long-run guard, exactly as before per-caller limits existed.
        self._entitlements = entitlements
        self._long_runs = long_runs
        # None (tests, older wiring) or disabled = nobody is on the paid plan.
        self._billing = billing

    async def execute(
        self,
        *,
        principal: Principal,
        accept_terms: bool,
        file: UploadedFile | None,
        url: str | None,
        gemini_api_key: str | None,
        device_token: str | None = None,
        client_ip: str = "",
    ) -> Run:
        if not accept_terms:
            raise TermsNotAcceptedError("Accept the media-use terms before analysis.")

        run_id = str(uuid.uuid4())
        source_url = url.strip() if url else None
        if (file is None) == (source_url is None):
            if file is not None:
                await file.close()
            raise InvalidSourceError("Provide exactly one source: either a media file or a public URL.")

        # The paid plan decides the counter, the media limits and the daily
        # cap below, with or without the caller's own key.
        paid = await self._paid_account(principal)
        # Nothing below this line may run for a caller who isn't allowed to
        # start one: no download, no FFmpeg, no budget spent.
        admission = await self._admit(
            principal=principal,
            gemini_api_key=gemini_api_key,
            device_token=device_token,
            client_ip=client_ip,
            paid=paid,
        )
        try:
            if admission is not None:
                # Held before the job is enqueued, so the pipeline can find it
                # however quickly the download fails: a link that cannot be
                # fetched hands the free run back (ProcessRunUseCase).
                await admission.allowance.hold(run_id, admission.claim)
            # Signed in + own key: the bigger set; anyone else: standard, with
            # a plain-words hint about what signing in / a key would unlock.
            limits = (
                self._entitlements.media_limits(principal, byok=bool(gemini_api_key), paid=paid is not None)
                if self._entitlements is not None
                else None
            )
            return await self._accept(
                run_id=run_id,
                principal=principal,
                file=file,
                source_url=source_url,
                gemini_api_key=gemini_api_key,
                limits=limits,
                # Paid runs are paid for (included in the plan, or billed as
                # an extra run), so the shared cap on free spend does not
                # apply to them (docs/backend/billing.md).
                exempt_daily_cap=paid is not None,
            )
        except Exception:
            # A rejected intake (over the daily cap, too long, unschedulable)
            # must not cost the caller one of their free runs. Drop the hold
            # first so nothing later can hand the same run back a second time.
            if admission is not None:
                await admission.allowance.release(run_id, refund=False)
                await admission.allowance.refund(admission.claim)
            raise

    async def _paid_account(self, principal: Principal) -> BillingAccount | None:
        if self._billing is None or not principal.authenticated or not principal.account_id:
            return None
        return await self._billing.paid_account(principal.account_id)

    async def _admit(
        self,
        *,
        principal: Principal,
        gemini_api_key: str | None,
        device_token: str | None,
        client_ip: str,
        paid: BillingAccount | None = None,
    ) -> _Admission | None:
        """Whether this caller may start a run on the shared Gemini key.

        The one seam a plan check slots into: "own key: always", "signed-in
        account: within today's account free runs", or "anyone else:
        within today's device free runs". Returns the free run taken, so it
        can be handed back if the intake is rejected after this point; None
        when nothing was taken.
        """
        # A caller-supplied key spends their own quota, not ours: never
        # counted against the paid plan's included runs, never billed.
        if gemini_api_key:
            return None
        accounts = self._account_free_runs
        if paid is not None and self._billing is not None and accounts is not None:
            return await self._admit_paid(paid, accounts)
        if principal.authenticated and principal.account_id and accounts is not None and accounts.enabled:
            # Instead of the device counter, never on top of it: no device
            # token needed, the device count is not touched, and no IP
            # backstop (the account is the identity; docs/backend/free-runs.md).
            account_claim = await accounts.try_consume(principal.account_id, period=FreeRunPeriod.DAY)
            if account_claim is None:
                status = await accounts.status(principal.account_id, period=FreeRunPeriod.DAY)
                raise FreeRunsExhaustedError(
                    ACCOUNT_FREE_RUNS_USED_MESSAGE,
                    limit=status.limit,
                    used=status.used,
                    scope=FreeRunScope.ACCOUNT.value,
                    period=FreeRunPeriod.DAY.value,
                )
            return _Admission(allowance=accounts, claim=account_claim)
        if not self._free_runs.enabled:
            return None
        device_id = self._device_tokens.verify(device_token or "")
        if device_id is None:
            raise DeviceTokenInvalidError("This device needs a fresh token. Reload and try again.")
        claim = await self._free_runs.try_consume(device_id, client_ip)
        if claim is None:
            status = await self._free_runs.status(device_id)
            # Same answer whichever counter tripped: the device's numbers.
            raise FreeRunsExhaustedError(
                FREE_RUNS_USED_MESSAGE,
                limit=status.limit,
                used=status.used,
                scope=FreeRunScope.DEVICE.value,
                period=FreeRunPeriod.DAY.value,
            )
        return _Admission(allowance=self._free_runs, claim=claim)

    async def _admit_paid(self, paid: BillingAccount, accounts: AccountFreeRunAllowance) -> _Admission:
        """The paid plan: the account's daily counter ("YYYY-MM-DD", the same
        row the free plan counts on, so a run is counted once whichever plan
        took it) with the plan's limit (`PAID_RUNS_PER_DAY`), then, past it,
        an extra run billed on completion. Never a 402 for running past the
        included runs; only the monthly safety cap on extra runs (keyed on
        the UTC month, not the day) refuses."""
        billing = self._billing
        assert billing is not None
        claim = await accounts.try_consume(
            paid.account_id, limit=billing.paid_runs_per_day, period=billing.paid_runs_period
        )
        if claim is not None:
            return _Admission(allowance=accounts, claim=claim)
        period = utc_month(billing.now())
        cap = billing.extra_runs_monthly_cap
        if cap > 0 and await billing.ledger.count(paid.account_id, period) >= cap:
            raise ExtraRunsCapReachedError(EXTRA_RUNS_CAP_MESSAGE, limit=cap)
        return _Admission(allowance=_ExtraRunHold(billing.ledger, paid, period), claim=None)

    async def _accept(
        self,
        *,
        run_id: str,
        principal: Principal,
        file: UploadedFile | None,
        source_url: str | None,
        gemini_api_key: str | None,
        limits: MediaLimits | None = None,
        exempt_daily_cap: bool = False,
    ) -> Run:
        # BYOK runs skip the daily budget too: it exists purely to bound our
        # own Gemini spend. So do paid runs (`exempt_daily_cap`).
        if not gemini_api_key and not exempt_daily_cap and not await self._spend_cap.try_consume():
            raise QuotaExceededError(
                "VideoLens AI has reached its limit for today. Add your own Gemini key "
                "from the menu to keep going, or try again tomorrow.",
                # The budget is per UTC day (DailyBudget), so it frees at midnight UTC.
                retry_after_seconds=seconds_until_next_utc_day(datetime.now(timezone.utc)),
            )

        saved = None
        source_key = None
        platform = None
        duration_seconds = None
        slot_key = None
        try:
            if file is not None:
                saved = await self._media.save_upload(run_id, file, limits)
                duration_seconds = await self._media.enforce_duration_cap(run_id, saved.path, limits)
                slot_key = await self._claim_long_run(run_id, limits, duration_seconds, saved.size_bytes)
                # Only the extension of the *saved* path is consulted (the
                # adapter names it "upload<ext>"), never the submitted
                # filename, which can carry personal information.
                platform = file_platform(os.path.splitext(saved.path)[1])
                if self._distributed:
                    source_key = await self._storage.upload_source(run_id, saved.path)
                    self._media.cleanup_run_dir(run_id)

            run = await self._runs.create(
                run_id,
                principal.subject,
                source_kind="file" if file is not None else "link",
                platform=platform,
                duration_seconds=duration_seconds,
                media_tier=limits.tier.value if limits is not None else None,
                # Recorded so the worker never runs it on the shared key: it
                # skipped the free-run and daily-cap checks above.
                admitted_byok=bool(gemini_api_key),
            )
            await self._queue.enqueue(
                run_id,
                saved_path=saved.path if saved and not self._distributed else None,
                run_dir=saved.run_dir if saved and not self._distributed else None,
                source_url=source_url,
                source_key=source_key,
                gemini_api_key=gemini_api_key,
                limits=limits,
            )
            return run
        except (MediaValidationError, LongRunInProgressError):
            await self._release_long_run(slot_key, run_id)
            self._media.cleanup_run_dir(run_id)
            raise
        except Exception as exc:
            await self._release_long_run(slot_key, run_id)
            self._media.cleanup_run_dir(run_id)
            if source_key:
                await self._storage.delete_source(source_key)
            raise RunSchedulingError("VideoLens is having trouble right now. Try again in a moment.") from exc

    async def _claim_long_run(
        self,
        run_id: str,
        limits: MediaLimits | None,
        duration_seconds: float | None,
        size_bytes: int | None,
    ) -> str | None:
        """Take the account's one long-run slot when this upload is above the
        standard limits. Returns the slot key it holds, or None when the run
        is standard-length (never refused for the guard) or not on the bigger
        tier. A link's length is unknown here; the worker claims for it."""
        if limits is None or not limits.long_run_key or self._entitlements is None or self._long_runs is None:
            return None
        if not self._entitlements.is_long(duration_seconds=duration_seconds, size_bytes=size_bytes):
            return None
        if not await self._long_runs.try_acquire(limits.long_run_key, run_id):
            raise LongRunInProgressError()
        return limits.long_run_key

    async def _release_long_run(self, slot_key: str | None, run_id: str) -> None:
        if slot_key is None or self._long_runs is None:
            return
        try:
            await self._long_runs.release(slot_key, run_id)
        except Exception:  # noqa: BLE001 - the slot expires on its own
            pass
