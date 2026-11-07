import jwt
from jwt import PyJWKClient

from ..config import Settings


class AuthNotConfiguredError(RuntimeError):
    pass


# How long a fetched JWK set is reused before the endpoint is asked again. A
# rotated key not yet in the cache is fetched on a miss regardless (PyJWKClient
# refreshes when a token names an unknown kid), so this only bounds how often
# the common case talks to the identity provider.
_JWKS_LIFESPAN_SECONDS = 600


class JwtVerifier:
    """TokenVerifier adapter backed by a remote JWKS endpoint (OIDC).

    One `PyJWKClient` for the lifetime of the verifier: it caches the key set,
    so the provider is asked once per cache lifetime rather than once per
    request. Building a client per call (as this used to) fetched the JWKS on
    every authenticated request, which is a round trip of latency per call and
    hands anyone with a token a way to make this service hammer the provider.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_client: PyJWKClient | None = None

    def _client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(
                self._settings.auth_jwks_url, cache_keys=True, lifespan=_JWKS_LIFESPAN_SECONDS
            )
        return self._jwks_client

    def decode(self, token: str) -> dict:
        settings = self._settings
        if not settings.auth_jwks_url or not settings.auth_issuer or not settings.auth_audience:
            raise AuthNotConfiguredError("Authentication is not configured.")
        signing_key = self._client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
        )
