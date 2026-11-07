import unittest
from unittest.mock import MagicMock, patch

from app.infrastructure.auth.jwt_verifier import AuthNotConfiguredError, JwtVerifier
from app.infrastructure.config import Settings


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
        jwk_client.return_value.get_signing_key_from_jwt.return_value = MagicMock(key="k")
        verifier = JwtVerifier(_configured())

        verifier.decode("a.b.c")
        verifier.decode("d.e.f")

        jwk_client.assert_called_once()
        _, kwargs = jwk_client.call_args
        self.assertTrue(kwargs["cache_keys"])
        self.assertGreater(kwargs["lifespan"], 0)
        self.assertEqual(jwk_client.return_value.get_signing_key_from_jwt.call_count, 2)

    @patch("app.infrastructure.auth.jwt_verifier.jwt.decode", return_value={"sub": "u1"})
    @patch("app.infrastructure.auth.jwt_verifier.PyJWKClient")
    def test_only_asymmetric_algorithms_are_accepted(self, jwk_client, decode) -> None:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = MagicMock(key="k")

        JwtVerifier(_configured()).decode("a.b.c")

        _, kwargs = decode.call_args
        self.assertEqual(set(kwargs["algorithms"]), {"RS256", "ES256"})
        self.assertEqual(kwargs["audience"], "videolens")
        self.assertEqual(kwargs["issuer"], "https://idp.example/")


if __name__ == "__main__":
    unittest.main()
