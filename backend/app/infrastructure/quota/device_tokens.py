import base64
import hashlib
import hmac
import logging
import re
import secrets

from ..config import Settings

logger = logging.getLogger("videolens")

_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# A real token is ~66 characters; anything far longer is not worth hashing.
_MAX_TOKEN_LENGTH = 256


class HmacDeviceTokens:
    """DeviceTokenSigner adapter: `<random id>.<HMAC-SHA256(secret, id)>`,
    both halves base64url without padding.

    Stateless on purpose - nothing is stored per device until it actually
    spends a free run, and any replica holding the same secret can verify a
    token another replica issued. The signature is what stops a client from
    inventing a fresh device id for every request; it does not stop a client
    from asking for a fresh *token* (that is what the per-IP backstop is for).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        configured = settings.device_token_secret.strip()
        self._generated = not configured
        self._secret = (configured or secrets.token_urlsafe(32)).encode()

    def validate_configuration(self) -> None:
        """Startup check. A per-process secret is fine for one local process
        and fatal for several: each replica would reject the others' tokens,
        so free-run callers would get a 401 on every other request."""
        if not self._generated or self._settings.free_runs_per_device <= 0:
            return
        if self._settings.queue_enabled:
            raise RuntimeError(
                "DEVICE_TOKEN_SECRET must be set when REDIS_URL is set and FREE_RUNS_PER_DEVICE > 0: "
                "every replica has to sign device tokens with the same key. Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"`, or set "
                "FREE_RUNS_PER_DEVICE=0 to turn free runs off."
            )
        logger.warning(
            "DEVICE_TOKEN_SECRET is not set; using a random per-process key. Device tokens "
            "issued before a restart will be re-issued. Set it for any shared deployment."
        )

    def issue(self) -> str:
        device_id = secrets.token_urlsafe(16)
        return f"{device_id}.{self._sign(device_id)}"

    def verify(self, token: str) -> str | None:
        if not token or len(token) > _MAX_TOKEN_LENGTH:
            return None
        device_id, dot, signature = token.strip().partition(".")
        if not dot or not _DEVICE_ID.fullmatch(device_id):
            return None
        if not hmac.compare_digest(signature.encode(), self._sign(device_id).encode()):
            return None
        return device_id

    def _sign(self, device_id: str) -> str:
        digest = hmac.new(self._secret, device_id.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
