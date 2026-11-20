import logging
import threading
import time

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidAlgorithmError, InvalidTokenError, PyJWKClientError

# Re-exported for callers that imported it from here before it moved to the
# domain (where the API layer can catch it without importing this adapter).
from ...domain.errors import AuthNotConfiguredError, AuthUnavailableError
from ..config import Settings

__all__ = ["AuthNotConfiguredError", "AuthUnavailableError", "JwtVerifier"]

logger = logging.getLogger("videolens")

# How long a fetched JWK set is reused before the endpoint is asked again.
_JWKS_LIFESPAN_SECONDS = 600

# A token naming a kid the cached set does not hold forces a refetch (that is
# how a rotated signing key is picked up), but at most once per this window
# per process. PyJWKClient's own `get_signing_key_from_jwt` refetches on every
# miss, so a loop of tokens with made-up kids would turn this API into a JWKS
# hammer: the limiter never sees a request that 401s in `get_principal`.
_FORCED_REFRESH_INTERVAL_SECONDS = 60

# Bounds a single fetch (PyJWT's default is 30s, one executor thread each).
_JWKS_FETCH_TIMEOUT_SECONDS = 5

# Stale-while-error. When a fetch fails the last good key set keeps verifying
# tokens for up to this long after it was fetched, so a JWKS outage does not
# sign everyone out; past it (or with no key set ever fetched) a token is
# answered 503 `AuthUnavailableError`, not 401, because it may well be valid.
# Bounded so a key the provider revoked during a long outage is not trusted
# for ever.
_JWKS_MAX_STALE_SECONDS = 6 * 60 * 60

# After a failed fetch nothing is fetched again for this long: requests are
# served from the stale set (or refused 503) without each one waiting out the
# fetch timeout on its own executor thread.
_JWKS_RETRY_AFTER_FAILURE_SECONDS = 30

# Asymmetric only, on purpose. HS256 would mean holding the provider's shared
# secret on this service (legacy Supabase projects sign that way: rotate them
# to an ES256 key, never add HS256 here), and `none` is never acceptable.
_ALGORITHMS = ["RS256", "ES256"]

# Clock skew tolerated on exp/iat/nbf between the provider and this service.
_LEEWAY_SECONDS = 30

# Claims a token must carry to be accepted at all.
_REQUIRED_CLAIMS = ["exp", "iat", "sub"]


class JwtVerifier:
    """TokenVerifier adapter backed by a remote JWKS endpoint (OIDC).

    One `PyJWKClient` for the lifetime of the verifier: it caches the key set,
    so the provider is asked once per cache lifetime rather than once per
    request. Building a client per call (as this used to) fetched the JWKS on
    every authenticated request, which is a round trip of latency per call and
    hands anyone with a token a way to make this service hammer the provider.

    The JWKS URL and issuer are required. The audience is enforced whenever
    `AUTH_AUDIENCE` is set (Supabase: `authenticated`); with it blank the
    check is skipped rather than every token failing on a claim nobody
    configured. `iss` is always checked, so a token from another of the
    owner's Supabase projects fails here.

    A JWKS outage (`_keys`): the last good key set is served for up to
    `_JWKS_MAX_STALE_SECONDS`, refetching at most once per
    `_JWKS_RETRY_AFTER_FAILURE_SECONDS`; with no usable set the token is
    refused with `AuthUnavailableError` (503), which the failed-credential
    limiter does not count. A token that fails verification against keys in
    hand is still a 401.

    Never logs a token: on rejection, the `kid` and the failure class only.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_client: PyJWKClient | None = None
        self._refresh_lock = threading.Lock()
        self._last_forced_refresh: float | None = None
        self._state_lock = threading.Lock()
        self._good_keys: list | None = None
        self._good_at: float | None = None
        self._failed_at: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self._settings.auth_jwks_url and self._settings.auth_issuer)

    def _client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(
                self._settings.auth_jwks_url,
                cache_keys=True,
                lifespan=_JWKS_LIFESPAN_SECONDS,
                timeout=_JWKS_FETCH_TIMEOUT_SECONDS,
            )
        return self._jwks_client

    def decode(self, token: str) -> dict:
        if not self.configured:
            raise AuthNotConfiguredError("Authentication is not configured.")
        try:
            return self.decode_with_key(token, self._signing_key(token))
        except AuthUnavailableError:
            raise
        except Exception as exc:
            logger.info("JWT rejected: %s (kid=%s)", type(exc).__name__, _kid(token))
            raise

    def _signing_key(self, token: str):
        """The public key for `token`, from the cached JWK set.

        The header is screened before any key lookup: a disallowed `alg` or a
        missing `kid` is refused without touching the network. An unknown kid
        forces one refetch (key rotation), then nothing until the window
        passes; tokens with an unknown kid in between are simply refused.
        While the JWKS cannot be fetched an unknown kid cannot be told from a
        rotated one, so it is `AuthUnavailableError` (503), not a 401.
        """
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in _ALGORITHMS:
            raise InvalidAlgorithmError("The token's algorithm is not allowed.")
        kid = header.get("kid")
        if not kid or not isinstance(kid, str):
            raise InvalidTokenError("The token names no signing key.")
        keys, current = self._keys()
        key = _find(keys, kid)
        if key is None and current and self._may_force_refresh():
            keys, current = self._keys(refresh=True)
            key = _find(keys, kid)
        if key is None:
            if not current:
                raise AuthUnavailableError(
                    "Sign-in is unavailable right now. Try again in a moment.",
                    retry_after_seconds=_JWKS_RETRY_AFTER_FAILURE_SECONDS,
                )
            raise PyJWKClientError("Unknown signing key.")
        return key.key

    def _keys(self, *, refresh: bool = False) -> tuple[list, bool]:
        """The signing keys and whether they are current (the last fetch
        worked). `PyJWKClient` caches a good set for `_JWKS_LIFESPAN_SECONDS`;
        this adds the outage rules on top. Raises `AuthUnavailableError` when
        there is no set to serve."""
        now = time.monotonic()
        with self._state_lock:
            failed_recently = (
                self._failed_at is not None and now - self._failed_at < _JWKS_RETRY_AFTER_FAILURE_SECONDS
            )
        if not failed_recently:
            try:
                keys = self._client().get_signing_keys(refresh=True) if refresh else self._client().get_signing_keys()
            except Exception as exc:  # noqa: BLE001 - unreachable, timed out, or not a usable key set
                with self._state_lock:
                    self._failed_at = now
                logger.warning("JWKS fetch failed (%s); serving the last good key set if any", type(exc).__name__)
            else:
                with self._state_lock:
                    self._good_keys, self._good_at, self._failed_at = list(keys), now, None
                return list(keys), True
        with self._state_lock:
            keys, good_at = self._good_keys, self._good_at
        if keys is not None and good_at is not None and now - good_at < _JWKS_MAX_STALE_SECONDS:
            return keys, False
        raise AuthUnavailableError(
            "Sign-in is unavailable right now. Try again in a moment.",
            retry_after_seconds=_JWKS_RETRY_AFTER_FAILURE_SECONDS,
        )

    def _may_force_refresh(self) -> bool:
        with self._refresh_lock:
            now = time.monotonic()
            last = self._last_forced_refresh
            if last is not None and now - last < _FORCED_REFRESH_INTERVAL_SECONDS:
                return False
            self._last_forced_refresh = now
            return True

    def decode_with_key(self, token: str, key) -> dict:
        """Verify `token` against an already-resolved public key: `decode` is
        the JWKS lookup plus this. Split out so the claim rules can be tested
        with a locally generated key and no JWKS endpoint."""
        settings = self._settings
        return jwt.decode(
            token,
            key,
            algorithms=_ALGORITHMS,
            audience=settings.auth_audience or None,
            issuer=settings.auth_issuer,
            leeway=_LEEWAY_SECONDS,
            options={"require": list(_REQUIRED_CLAIMS), "verify_aud": bool(settings.auth_audience)},
        )

    def fetch_key_count(self) -> int:
        """Fetch (or reuse the cached) JWK set and return how many keys it
        holds. For the `auth` capability probe; raises when unreachable."""
        return len(self._client().get_jwk_set().keys)


def _find(keys, kid: str):
    return next((key for key in keys if key.key_id == kid), None)


def _kid(token: str) -> str:
    try:
        return str(jwt.get_unverified_header(token).get("kid", "-"))
    except Exception:  # noqa: BLE001 - a malformed header has no kid to report
        return "-"
