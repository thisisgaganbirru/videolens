import time
import unittest
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.domain.errors import AuthNotConfiguredError as DomainAuthNotConfiguredError
from app.infrastructure.auth.jwt_verifier import AuthNotConfiguredError, JwtVerifier
from app.infrastructure.config import Settings

ISSUER = "https://abcd.supabase.co/auth/v1"
AUDIENCE = "authenticated"
_KEY = ec.generate_private_key(ec.SECP256R1())


def _supabase(**overrides) -> Settings:
    values = {
        "auth_jwks_url": f"{ISSUER}/.well-known/jwks.json",
        "auth_issuer": ISSUER,
        "auth_audience": AUDIENCE,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _token(*, key=_KEY, algorithm="ES256", drop=(), **claims) -> str:
    now = int(time.time())
    payload = {"sub": "user-123", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 3600, "role": "authenticated"}
    payload.update(claims)
    for name in drop:
        payload.pop(name, None)
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": "kid-1"})


def _configured() -> Settings:
    return Settings(
        _env_file=None,
        auth_jwks_url="https://idp.example/.well-known/jwks.json",
        auth_issuer="https://idp.example/",
        auth_audience="videolens",
    )


class JwtVerifierTests(unittest.TestCase):
    def test_unconfigured_auth_is_a_distinct_error(self) -> None:
        with self.assertRaises(AuthNotConfiguredError):
            JwtVerifier(Settings(_env_file=None)).decode("x.y.z")

    @patch("app.infrastructure.auth.jwt_verifier.jwt.decode", return_value={"sub": "u1"})
    @patch("app.infrastructure.auth.jwt_verifier.PyJWKClient")
    def test_reuses_one_caching_jwks_client_across_requests(self, jwk_client, _decode) -> None:
        # One client for the verifier's lifetime, built to cache the key set:
        # a client per call fetched the JWKS on every authenticated request.
        jwk_client.return_value.get_signing_keys.return_value = [MagicMock(key_id="kid-1", key="k")]
        verifier = JwtVerifier(_configured())

        verifier.decode(_token())
        verifier.decode(_token())

        jwk_client.assert_called_once()
        _, kwargs = jwk_client.call_args
        self.assertTrue(kwargs["cache_keys"])
        self.assertGreater(kwargs["lifespan"], 0)
        self.assertEqual(kwargs["timeout"], 5)
        self.assertEqual(jwk_client.return_value.get_signing_keys.call_count, 2)
        jwk_client.return_value.get_signing_keys.assert_called_with()

    @patch("app.infrastructure.auth.jwt_verifier.jwt.decode", return_value={"sub": "u1"})
    @patch("app.infrastructure.auth.jwt_verifier.PyJWKClient")
    def test_only_asymmetric_algorithms_are_accepted(self, jwk_client, decode) -> None:
        jwk_client.return_value.get_signing_keys.return_value = [MagicMock(key_id="kid-1", key="k")]

        JwtVerifier(_configured()).decode(_token())

        _, kwargs = decode.call_args
        self.assertEqual(set(kwargs["algorithms"]), {"RS256", "ES256"})
        self.assertEqual(kwargs["audience"], "videolens")
        self.assertEqual(kwargs["issuer"], "https://idp.example/")

    def test_not_configured_error_is_the_domain_type(self) -> None:
        # The API layer maps the domain type to 503; the adapter re-exports it.
        self.assertIs(AuthNotConfiguredError, DomainAuthNotConfiguredError)

    def test_audience_is_optional_but_jwks_and_issuer_are_not(self) -> None:
        self.assertTrue(JwtVerifier(_supabase(auth_audience="")).configured)
        self.assertFalse(JwtVerifier(_supabase(auth_issuer="")).configured)
        self.assertFalse(JwtVerifier(_supabase(auth_jwks_url="")).configured)


class ClaimRuleTests(unittest.TestCase):
    """The claim checks against a real ES256 key (Supabase's default for new
    projects), through `decode_with_key`, so no JWKS endpoint is needed."""

    def setUp(self) -> None:
        self.verifier = JwtVerifier(_supabase())
        self.public = _KEY.public_key()

    def test_a_valid_supabase_token_is_accepted(self) -> None:
        claims = self.verifier.decode_with_key(_token(), self.public)
        self.assertEqual(claims["sub"], "user-123")

    def test_expired_token_is_rejected(self) -> None:
        token = _token(exp=int(time.time()) - 120, iat=int(time.time()) - 3720)
        with self.assertRaises(jwt.ExpiredSignatureError):
            self.verifier.decode_with_key(token, self.public)

    def test_expiry_within_the_leeway_is_accepted(self) -> None:
        # Expired 10 s ago by this clock: inside the 30 s skew allowance.
        token = _token(exp=int(time.time()) - 10, iat=int(time.time()) - 3610)
        self.assertEqual(self.verifier.decode_with_key(token, self.public)["sub"], "user-123")

    def test_wrong_audience_is_rejected(self) -> None:
        with self.assertRaises(jwt.InvalidAudienceError):
            self.verifier.decode_with_key(_token(aud="anon"), self.public)

    def test_missing_audience_is_rejected_when_one_is_configured(self) -> None:
        with self.assertRaises(jwt.MissingRequiredClaimError):
            self.verifier.decode_with_key(_token(drop=("aud",)), self.public)

    def test_audience_is_not_checked_when_none_is_configured(self) -> None:
        verifier = JwtVerifier(_supabase(auth_audience=""))
        self.assertEqual(verifier.decode_with_key(_token(aud="anything"), self.public)["sub"], "user-123")

    def test_wrong_issuer_is_rejected(self) -> None:
        # A token from another of the owner's Supabase projects.
        with self.assertRaises(jwt.InvalidIssuerError):
            self.verifier.decode_with_key(_token(iss="https://other.supabase.co/auth/v1"), self.public)

    def test_missing_subject_is_rejected(self) -> None:
        with self.assertRaises(jwt.MissingRequiredClaimError):
            self.verifier.decode_with_key(_token(drop=("sub",)), self.public)

    def test_missing_exp_or_iat_is_rejected(self) -> None:
        for claim in ("exp", "iat"):
            with self.subTest(claim=claim), self.assertRaises(jwt.MissingRequiredClaimError):
                self.verifier.decode_with_key(_token(drop=(claim,)), self.public)

    def test_a_token_signed_by_another_key_is_rejected(self) -> None:
        other = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(jwt.InvalidSignatureError):
            self.verifier.decode_with_key(_token(key=other), self.public)

    def test_hs256_is_refused_by_construction(self) -> None:
        # A legacy Supabase project's shared-secret token never verifies.
        token = _token(key="shared-secret-of-a-legacy-project-0123456789", algorithm="HS256")
        with self.assertRaises(jwt.InvalidAlgorithmError):
            self.verifier.decode_with_key(token, "shared-secret-of-a-legacy-project-0123456789")

    @patch("app.infrastructure.auth.jwt_verifier.PyJWKClient")
    def test_rejection_logs_the_kid_and_failure_class_never_the_token(self, jwk_client) -> None:
        jwk_client.return_value.get_signing_keys.return_value = [MagicMock(key_id="kid-1", key=self.public)]
        token = _token(aud="anon")
        with self.assertLogs("videolens", level="INFO") as logs, self.assertRaises(jwt.InvalidAudienceError):
            self.verifier.decode(token)
        output = " ".join(logs.output)
        self.assertIn("kid-1", output)
        self.assertIn("InvalidAudienceError", output)
        self.assertNotIn(token, output)


def _header_only(header: dict) -> str:
    """A token-shaped string with any header: the signature is never checked
    because the header screen refuses it first."""
    import base64
    import json

    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{b64(header)}.{b64({'sub': 'x'})}.c2ln"


class JwksRefreshThrottleTests(unittest.TestCase):
    """A token naming an unknown kid must not make every request refetch the
    JWKS: the 401 never reaches the rate limiter."""

    def setUp(self) -> None:
        patcher = patch("app.infrastructure.auth.jwt_verifier.PyJWKClient")
        self.client = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.client.get_signing_keys.return_value = [MagicMock(key_id="kid-1", key=_KEY.public_key())]
        self.verifier = JwtVerifier(_supabase())

    def _forced(self) -> int:
        return sum(1 for call in self.client.get_signing_keys.call_args_list if call.kwargs.get("refresh"))

    def test_unknown_kid_forces_at_most_one_refetch_per_window(self) -> None:
        forged = _header_only({"alg": "ES256", "kid": "made-up"})
        for _ in range(20):
            with self.assertRaises(jwt.PyJWKClientError):
                self.verifier.decode(forged)
        self.assertEqual(self._forced(), 1)

        # A valid token keeps working from the cache in between.
        self.assertEqual(self.verifier.decode(_token())["sub"], "user-123")
        self.assertEqual(self._forced(), 1)

        with patch("app.infrastructure.auth.jwt_verifier.time.monotonic", return_value=time.monotonic() + 61):
            with self.assertRaises(jwt.PyJWKClientError):
                self.verifier.decode(forged)
        self.assertEqual(self._forced(), 2)

    def test_a_rotated_key_is_picked_up_by_the_forced_refresh(self) -> None:
        rotated = ec.generate_private_key(ec.SECP256R1())
        old = [MagicMock(key_id="kid-1", key=_KEY.public_key())]
        new = old + [MagicMock(key_id="kid-2", key=rotated.public_key())]
        self.client.get_signing_keys.side_effect = lambda refresh=False: new if refresh else old
        now = int(time.time())
        token = jwt.encode(
            {"sub": "user-123", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 3600},
            rotated,
            algorithm="ES256",
            headers={"kid": "kid-2"},
        )
        self.assertEqual(self.verifier.decode(token)["sub"], "user-123")
        self.assertEqual(self._forced(), 1)

    def test_missing_kid_never_fetches(self) -> None:
        for header in ({"alg": "ES256"}, {"alg": "ES256", "kid": ""}, {"alg": "ES256", "kid": 7}):
            with self.subTest(header=header), self.assertRaises(jwt.InvalidTokenError):
                self.verifier.decode(_header_only(header))
        self.client.get_signing_keys.assert_not_called()

    def test_disallowed_algorithm_never_fetches(self) -> None:
        for alg in ("HS256", "none", None):
            with self.subTest(alg=alg), self.assertRaises(jwt.InvalidAlgorithmError):
                self.verifier.decode(_header_only({"alg": alg, "kid": "kid-1"}))
        self.client.get_signing_keys.assert_not_called()

    def test_malformed_token_never_fetches(self) -> None:
        with self.assertRaises(jwt.DecodeError):
            self.verifier.decode("not-a-token")
        self.client.get_signing_keys.assert_not_called()


if __name__ == "__main__":
    unittest.main()
