import unittest

from app.infrastructure.config import Settings
from app.infrastructure.storage.s3_object_store import S3ObjectStore


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        s3_endpoint_url="https://t3.storageapi.dev",
        s3_bucket="media-abc",
        s3_access_key_id="key",
        s3_secret_access_key="secret",
        **overrides,
    )


class AddressingStyleTests(unittest.TestCase):
    """Presigning builds the request URL without any network call, so it shows
    which host and path the client would actually contact."""

    def _url(self, settings: Settings) -> str:
        client = S3ObjectStore(settings)._client()
        return client.generate_presigned_url("head_bucket", Params={"Bucket": "media-abc"})

    def test_default_keeps_path_style_for_minio(self) -> None:
        self.assertTrue(self._url(_settings()).startswith("https://t3.storageapi.dev/media-abc"))

    def test_virtual_puts_the_bucket_in_the_host(self) -> None:
        url = self._url(_settings(s3_addressing_style="virtual"))
        self.assertTrue(url.startswith("https://media-abc.t3.storageapi.dev/"))
