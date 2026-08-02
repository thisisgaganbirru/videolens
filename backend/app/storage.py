import asyncio
import os

import boto3

from .config import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
    )


async def upload_source(run_id: str, path: str) -> str:
    if not settings.object_storage_enabled:
        raise RuntimeError("Object storage is not configured.")
    extension = os.path.splitext(path)[1].lower()
    key = f"runs/{run_id}/source{extension}"
    await asyncio.to_thread(_client().upload_file, path, settings.s3_bucket, key)
    return key


async def download_source(key: str, destination: str) -> None:
    await asyncio.to_thread(_client().download_file, settings.s3_bucket, key, destination)


async def delete_source(key: str) -> None:
    if settings.object_storage_enabled:
        await asyncio.to_thread(_client().delete_object, Bucket=settings.s3_bucket, Key=key)
