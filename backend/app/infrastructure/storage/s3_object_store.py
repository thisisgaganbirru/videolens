import asyncio
import os

import boto3

from ..config import Settings


class S3ObjectStore:
    """ObjectStore adapter backed by an S3-compatible bucket."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key_id,
            aws_secret_access_key=self._settings.s3_secret_access_key,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.object_storage_enabled

    async def check_bucket(self) -> None:
        """Contact the bucket. Raises if the endpoint, credentials, or bucket
        name are wrong - which is the whole point: having the four settings
        filled in says nothing about whether they are correct."""
        if not self.enabled:
            raise RuntimeError("Object storage is not configured.")
        await asyncio.to_thread(self._client().head_bucket, Bucket=self._settings.s3_bucket)

    async def upload_source(self, run_id: str, path: str) -> str:
        if not self.enabled:
            raise RuntimeError("Object storage is not configured.")
        extension = os.path.splitext(path)[1].lower()
        key = f"runs/{run_id}/source{extension}"
        await asyncio.to_thread(self._client().upload_file, path, self._settings.s3_bucket, key)
        return key

    async def download_source(self, key: str, destination: str) -> None:
        await asyncio.to_thread(self._client().download_file, self._settings.s3_bucket, key, destination)

    async def delete_source(self, key: str) -> None:
        if self.enabled:
            await asyncio.to_thread(self._client().delete_object, Bucket=self._settings.s3_bucket, Key=key)
