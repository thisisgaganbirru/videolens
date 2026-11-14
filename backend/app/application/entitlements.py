"""Turns "who is calling" into "what are they allowed to do".

One plan in auth phase 1, so every caller gets the same plan answer: the
deployment's own limits. The seam is kept so the subscription work replaces
the numbers (and reads the workspace's plan here), not the structure.

A paid account (docs/backend/billing.md) gets the `PAID_*` set (by default
the signed-in BYOK numbers) without needing a key. So does a complimentary
Plus account (same plan, `metered` false: it is never billed).

Media limits are per request on top of that (docs/backend/media-validation.md,
"Limits per caller"): a signed-in caller who brings their own Gemini key on
this run gets the bigger set (`SIGNED_IN_BYOK_*`), everyone else the
standard `MAX_DURATION_SECONDS` / `MAX_FILE_SIZE_MB`. Every enforcement point
(upload size, duration probe, URL download, caption fallback) reads the
`MediaLimits` chosen here, never the settings directly.
"""

from dataclasses import replace

from ..domain.entities import Principal
from ..domain.entitlements import Entitlement, MediaLimits, MediaTier, Plan, entitlement_for


class EntitlementResolver:
    def __init__(
        self,
        *,
        max_duration_seconds: int,
        max_file_size_mb: int,
        signed_in_byok_max_duration_seconds: int | None = None,
        signed_in_byok_max_file_size_mb: int | None = None,
        paid_max_duration_seconds: int | None = None,
        paid_max_file_size_mb: int | None = None,
    ) -> None:
        self._max_duration_seconds = max_duration_seconds
        self._max_file_size_mb = max_file_size_mb
        # Never lower than standard: a misconfigured (smaller) bigger tier
        # would otherwise punish exactly the callers it exists to reward.
        self._byok_duration = max(signed_in_byok_max_duration_seconds or 0, max_duration_seconds)
        self._byok_size = max(signed_in_byok_max_file_size_mb or 0, max_file_size_mb)
        # The paid plan: its own numbers when set (> 0), else the signed-in
        # BYOK ones; never below standard either.
        self._paid_duration = max(
            paid_max_duration_seconds if paid_max_duration_seconds and paid_max_duration_seconds > 0 else self._byok_duration,
            max_duration_seconds,
        )
        self._paid_size = max(
            paid_max_file_size_mb if paid_max_file_size_mb and paid_max_file_size_mb > 0 else self._byok_size,
            max_file_size_mb,
        )

    async def for_principal(
        self, principal: Principal, *, paid: bool = False, complimentary: bool = False
    ) -> Entitlement:
        if paid or complimentary:
            entitlement = entitlement_for(
                Plan.PAID, max_duration_seconds=self._paid_duration, max_file_size_mb=self._paid_size
            )
            # Complimentary Plus: nothing past the included runs is billed.
            return replace(entitlement, metered=False) if complimentary else entitlement
        return entitlement_for(
            Plan.FREE,
            max_duration_seconds=self._max_duration_seconds,
            max_file_size_mb=self._max_file_size_mb,
        )

    @property
    def standard(self) -> MediaLimits:
        return MediaLimits(
            tier=MediaTier.STANDARD,
            max_duration_seconds=self._max_duration_seconds,
            max_file_size_mb=self._max_file_size_mb,
        )

    @property
    def signed_in_byok(self) -> MediaLimits:
        return MediaLimits(
            tier=MediaTier.SIGNED_IN_BYOK,
            max_duration_seconds=self._byok_duration,
            max_file_size_mb=self._byok_size,
        )

    @property
    def paid(self) -> MediaLimits:
        return MediaLimits(
            tier=MediaTier.PAID,
            max_duration_seconds=self._paid_duration,
            max_file_size_mb=self._paid_size,
        )

    @property
    def has_bigger_tier(self) -> bool:
        return (self._byok_duration, self._byok_size) != (self._max_duration_seconds, self._max_file_size_mb)

    def is_long(self, *, duration_seconds: float | None = None, size_bytes: int | None = None) -> bool:
        """Above the standard limits: what the one-long-run-per-account
        guard counts."""
        standard = self.standard
        if duration_seconds is not None and duration_seconds > standard.max_duration_seconds:
            return True
        return size_bytes is not None and size_bytes > standard.max_file_size_bytes

    def media_limits(self, principal: Principal, *, byok: bool, paid: bool = False) -> MediaLimits:
        """The limits this request runs under, with the plain-words hint for
        a caller who would reach the bigger set by signing in or adding a key.
        `paid`: the account is on the paid plan, so it gets the paid set
        with or without its own key (the bigger of the two when it sends one)."""
        signed_in = principal.authenticated
        if signed_in and paid:
            duration, size = self._paid_duration, self._paid_size
            if byok:
                duration, size = max(duration, self._byok_duration), max(size, self._byok_size)
            if (duration, size) == (self._max_duration_seconds, self._max_file_size_mb):
                return self.standard
            return MediaLimits(
                tier=MediaTier.PAID,
                max_duration_seconds=duration,
                max_file_size_mb=size,
                long_run_key=principal.account_id or principal.subject,
            )
        if signed_in and byok:
            bigger = self.signed_in_byok
            if not self.has_bigger_tier:
                return self.standard
            return MediaLimits(
                tier=bigger.tier,
                max_duration_seconds=bigger.max_duration_seconds,
                max_file_size_mb=bigger.max_file_size_mb,
                # Per account, so two API keys of one person share the slot.
                long_run_key=principal.account_id or principal.subject,
            )
        standard = self.standard
        if not self.has_bigger_tier:
            return standard
        if signed_in:
            action = "Add your own Gemini key"
        elif byok:
            action = "Sign in"
        else:
            action = "Sign in and add your own Gemini key"
        return MediaLimits(
            tier=MediaTier.STANDARD,
            max_duration_seconds=standard.max_duration_seconds,
            max_file_size_mb=standard.max_file_size_mb,
            upgrade_action=action,
            upgrade_max_duration_seconds=self._byok_duration,
            upgrade_max_file_size_mb=self._byok_size,
        )
