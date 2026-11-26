import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

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


class ObjectStoreCallTests(unittest.IsolatedAsyncioTestCase):
    """What the adapter asks boto3 for, over a mocked client: never the network."""

    def setUp(self) -> None:
        self.client = MagicMock()
        patcher = patch.object(S3ObjectStore, "_client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_an_unconfigured_store_refuses_to_check_or_upload_and_deletes_nothing(self) -> None:
        store = S3ObjectStore(Settings(_env_file=None))
        self.assertFalse(store.enabled)
        with self.assertRaises(RuntimeError):
            await store.check_bucket()
        with self.assertRaises(RuntimeError):
            await store.upload_source("run-1", "/tmp/run-1/upload.mp4")
        await store.delete_source("runs/run-1/source.mp4")
        self.client.assert_not_called()
        self.assertEqual(self.client.method_calls, [])

    async def test_the_key_is_the_run_id_and_the_lowercased_extension_only(self) -> None:
        store = S3ObjectStore(_settings())
        key = await store.upload_source("run-1", "/tmp/run-1/My Clip.MOV")
        self.assertEqual(key, "runs/run-1/source.mov")
        self.client.upload_file.assert_called_once_with("/tmp/run-1/My Clip.MOV", "media-abc", "runs/run-1/source.mov")

    async def test_download_and_delete_use_the_configured_bucket(self) -> None:
        store = S3ObjectStore(_settings())
        await store.download_source("runs/run-1/source.mp4", "/tmp/run-1/source.mp4")
        await store.delete_source("runs/run-1/source.mp4")
        self.client.download_file.assert_called_once_with("media-abc", "runs/run-1/source.mp4", "/tmp/run-1/source.mp4")
        self.client.delete_object.assert_called_once_with(Bucket="media-abc", Key="runs/run-1/source.mp4")

    async def test_a_wrong_bucket_or_credentials_surface_from_check_bucket(self) -> None:
        # The readiness probe relies on this raising rather than passing quietly.
        self.client.head_bucket.side_effect = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket")
        with self.assertRaises(ClientError):
            await S3ObjectStore(_settings()).check_bucket()
        self.client.head_bucket.assert_called_once_with(Bucket="media-abc")
