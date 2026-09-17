"""The JWT adapter without a JWKS endpoint: the config gate and the claim
checks, exercised with a locally generated key pair."""

import unittest
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.auth.jwt_verifier import AuthNotConfiguredError, JwtVerifier
from app.infrastructure.config import Settings

ISSUER = "https://clerk.example.com"


def _settings(**overrides) -> Settings:
    fields = dict(auth_jwks_url=f"{ISSUER}/.well-known/jwks.json", auth_issuer=ISSUER)
    fields.update(overrides)
    return Settings(_env_file=None, **fields)


class JwtVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()

    def _token(self, **claims) -> str:
        payload = {
            "sub": "user_123",
            "iss": ISSUER,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        payload.update(claims)
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def test_refuses_to_decode_when_unconfigured(self) -> None:
        verifier = JwtVerifier(Settings(_env_file=None))
        with self.assertRaises(AuthNotConfiguredError):
            verifier.decode("anything")

    def test_issuer_alone_is_not_enough(self) -> None:
        verifier = JwtVerifier(Settings(_env_file=None, auth_issuer=ISSUER))
        with self.assertRaises(AuthNotConfiguredError):
            verifier.decode("anything")

    def test_accepts_token_without_audience_when_none_configured(self) -> None:
        # Clerk's default session token: iss + sub, no aud.
        claims = JwtVerifier(_settings()).decode_with_key(self._token(), self.public_key)
        self.assertEqual(claims["sub"], "user_123")

    def test_enforces_audience_when_configured(self) -> None:
        verifier = JwtVerifier(_settings(auth_audience="videolens-api"))
        with self.assertRaises(jwt.MissingRequiredClaimError):
            verifier.decode_with_key(self._token(), self.public_key)
        with self.assertRaises(jwt.InvalidAudienceError):
            verifier.decode_with_key(self._token(aud="someone-else"), self.public_key)
        claims = verifier.decode_with_key(self._token(aud="videolens-api"), self.public_key)
        self.assertEqual(claims["aud"], "videolens-api")

    def test_rejects_wrong_issuer(self) -> None:
        with self.assertRaises(jwt.InvalidIssuerError):
            JwtVerifier(_settings()).decode_with_key(
                self._token(iss="https://evil.example.com"), self.public_key
            )

    def test_rejects_wrong_key(self) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        with self.assertRaises(jwt.InvalidSignatureError):
            JwtVerifier(_settings()).decode_with_key(self._token(), other)
