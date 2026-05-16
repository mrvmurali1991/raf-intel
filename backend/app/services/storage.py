"""
Storage backend abstraction.

Defines a Protocol so upload logic can be swapped from local disk to S3/MinIO
without touching any upload routes. Currently not wired to any route — wiring
is a follow-up task.

Usage:
    from app.services.storage import get_storage_backend
    storage = get_storage_backend()
    url = storage.put("patient/abc/chart.pdf", pdf_bytes, "application/pdf")
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import settings


@runtime_checkable
class StorageBackend(Protocol):
    """Minimal interface every storage implementation must satisfy."""

    def put(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Write *data* to *path* and return the storage URL / key."""
        ...

    def get(self, path: str) -> bytes:
        """Return the raw bytes stored at *path*.

        Raises FileNotFoundError if the object does not exist.
        """
        ...

    def delete(self, path: str) -> None:
        """Remove the object at *path*.  No-op if it does not exist."""
        ...

    def exists(self, path: str) -> bool:
        """Return True if *path* exists in the backend."""
        ...

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        """Return a URL that grants temporary read access to *path*.

        For local storage a ``file://`` URL is returned (no real signing).
        For S3 a presigned GET URL valid for *expires_in* seconds is returned.
        """
        ...


# ---------------------------------------------------------------------------
# Local disk implementation
# ---------------------------------------------------------------------------

class LocalDiskStorage:
    """StorageBackend backed by the local filesystem.

    All objects are written under *root*, which defaults to
    ``settings.storage_local_root`` (``/app/uploads``).
    """

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or settings.storage_local_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        # Strip any leading slash so Path joining behaves predictably.
        return self._root / path.lstrip("/")

    def put(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",  # noqa: ARG002
    ) -> str:
        dest = self._resolve(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return str(dest)

    def get(self, path: str) -> bytes:
        dest = self._resolve(path)
        if not dest.exists():
            raise FileNotFoundError(f"Storage object not found: {path}")
        return dest.read_bytes()

    def delete(self, path: str) -> None:
        dest = self._resolve(path)
        if dest.exists():
            dest.unlink()

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def signed_url(self, path: str, expires_in: int = 3600) -> str:  # noqa: ARG002
        """Return a file:// URL (no real signing for local storage)."""
        return self._resolve(path).as_uri()


# ---------------------------------------------------------------------------
# S3 implementation
# ---------------------------------------------------------------------------

class S3Storage:
    """StorageBackend backed by Amazon S3 (or any S3-compatible store).

    ``boto3`` is lazy-imported so that environments without it (local dev) do
    not fail at import time — only at the moment an S3 operation is attempted.

    Authentication order follows the standard boto3 credential chain:
      1. Explicit ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` env vars.
      2. IAM instance role (recommended for production EC2/ECS).
      3. ``~/.aws/credentials``.
    """

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
    ) -> None:
        self._bucket = bucket or settings.storage_s3_bucket
        self._region = region or settings.storage_s3_region
        if not self._bucket:
            raise ValueError(
                "S3Storage requires a bucket name. "
                "Set STORAGE_S3_BUCKET in your environment."
            )
        self.__client = None  # lazily initialised

    @property
    def _client(self):  # type: ignore[return]
        if self.__client is None:
            try:
                import boto3  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "boto3 is required when STORAGE_BACKEND=s3. "
                    "Install it with: pip install 'boto3>=1.34.0'"
                ) from exc
            self.__client = boto3.client("s3", region_name=self._region)
        return self.__client

    def put(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        import io
        self._client.upload_fileobj(
            io.BytesIO(data),
            self._bucket,
            path,
            ExtraArgs={"ContentType": content_type},
        )
        return f"s3://{self._bucket}/{path}"

    def get(self, path: str) -> bytes:
        import botocore.exceptions  # type: ignore[import]
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=path)
            return response["Body"].read()
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"S3 object not found: s3://{self._bucket}/{path}") from exc
            raise

    def delete(self, path: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=path)

    def exists(self, path: str) -> bool:
        import botocore.exceptions  # type: ignore[import]
        try:
            self._client.head_object(Bucket=self._bucket, Key=path)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": path},
            ExpiresIn=expires_in,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend.

    Reads ``settings.storage_backend`` (env ``STORAGE_BACKEND``):
      * ``"local"`` (default) — LocalDiskStorage rooted at
        ``settings.storage_local_root``.
      * ``"s3"`` — S3Storage using ``settings.storage_s3_bucket`` /
        ``settings.storage_s3_region``.
    """
    backend = settings.storage_backend.lower()
    if backend == "s3":
        return S3Storage()
    if backend == "local":
        return LocalDiskStorage()
    raise ValueError(
        f"Unknown STORAGE_BACKEND={backend!r}. Valid values: 'local', 's3'."
    )
