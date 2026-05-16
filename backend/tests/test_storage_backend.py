"""
Tests for app.services.storage — StorageBackend protocol + implementations.

Run with:
    cd backend && pytest tests/test_storage_backend.py -v
"""
from __future__ import annotations

import importlib
import os
import pytest


# ---------------------------------------------------------------------------
# LocalDiskStorage round-trip
# ---------------------------------------------------------------------------

class TestLocalDiskStorage:
    def test_put_returns_absolute_path(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        result = storage.put("sub/hello.txt", b"hello world", "text/plain")
        assert result == str(tmp_path / "sub" / "hello.txt")

    def test_get_returns_written_bytes(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        storage.put("data.bin", b"\x00\x01\x02")
        assert storage.get("data.bin") == b"\x00\x01\x02"

    def test_exists_true_after_put(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        assert not storage.exists("missing.txt")
        storage.put("missing.txt", b"here now")
        assert storage.exists("missing.txt")

    def test_delete_removes_file(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        storage.put("remove_me.txt", b"bye")
        assert storage.exists("remove_me.txt")
        storage.delete("remove_me.txt")
        assert not storage.exists("remove_me.txt")

    def test_delete_nonexistent_is_noop(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        storage.delete("ghost.txt")  # must not raise

    def test_get_nonexistent_raises_file_not_found(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            storage.get("does_not_exist.txt")

    def test_signed_url_returns_file_uri(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        storage.put("doc.pdf", b"%PDF-1.4")
        url = storage.signed_url("doc.pdf")
        assert url.startswith("file://")
        assert "doc.pdf" in url

    def test_nested_path_creates_directories(self, tmp_path):
        from app.services.storage import LocalDiskStorage
        storage = LocalDiskStorage(root=str(tmp_path))
        storage.put("a/b/c/deep.txt", b"deep")
        assert storage.exists("a/b/c/deep.txt")

    def test_satisfies_protocol(self, tmp_path):
        from app.services.storage import LocalDiskStorage, StorageBackend
        storage = LocalDiskStorage(root=str(tmp_path))
        assert isinstance(storage, StorageBackend)


# ---------------------------------------------------------------------------
# S3Storage with moto (auto-skip when moto not installed)
# ---------------------------------------------------------------------------

class TestS3Storage:
    @pytest.fixture(autouse=True)
    def _require_moto(self):
        pytest.importorskip("moto", reason="moto not installed — skipping S3 tests")
        pytest.importorskip("boto3", reason="boto3 not installed — skipping S3 tests")

    @pytest.fixture()
    def s3_storage(self):
        import boto3
        from moto import mock_aws
        from app.services.storage import S3Storage

        with mock_aws():
            bucket = "test-raf-uploads"
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket)
            yield S3Storage(bucket=bucket, region="us-east-1")

    def test_put_returns_s3_uri(self, s3_storage):
        uri = s3_storage.put("patients/abc/chart.pdf", b"%PDF", "application/pdf")
        assert uri == "s3://test-raf-uploads/patients/abc/chart.pdf"

    def test_get_round_trip(self, s3_storage):
        s3_storage.put("file.bin", b"\xde\xad\xbe\xef")
        assert s3_storage.get("file.bin") == b"\xde\xad\xbe\xef"

    def test_exists_true_after_put(self, s3_storage):
        assert not s3_storage.exists("new.txt")
        s3_storage.put("new.txt", b"data")
        assert s3_storage.exists("new.txt")

    def test_delete_removes_object(self, s3_storage):
        s3_storage.put("del.txt", b"bye")
        s3_storage.delete("del.txt")
        assert not s3_storage.exists("del.txt")

    def test_get_missing_raises_file_not_found(self, s3_storage):
        with pytest.raises(FileNotFoundError):
            s3_storage.get("ghost.txt")

    def test_signed_url_is_https(self, s3_storage):
        s3_storage.put("doc.pdf", b"%PDF-1.4")
        url = s3_storage.signed_url("doc.pdf", expires_in=60)
        assert url.startswith("https://")
        assert "doc.pdf" in url

    def test_satisfies_protocol(self, s3_storage):
        from app.services.storage import StorageBackend
        assert isinstance(s3_storage, StorageBackend)

    def test_missing_bucket_raises_value_error(self):
        import boto3
        from moto import mock_aws
        from app.services.storage import S3Storage

        with mock_aws():
            with pytest.raises(ValueError, match="bucket"):
                S3Storage(bucket="", region="us-east-1")


# ---------------------------------------------------------------------------
# Factory: get_storage_backend()
# ---------------------------------------------------------------------------

class TestGetStorageBackend:
    def test_returns_local_by_default(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.storage_backend", "local")
        from app.services.storage import get_storage_backend, LocalDiskStorage
        backend = get_storage_backend()
        assert isinstance(backend, LocalDiskStorage)

    def test_returns_s3_when_configured(self, monkeypatch):
        pytest.importorskip("boto3", reason="boto3 not installed")
        pytest.importorskip("moto", reason="moto not installed")
        import boto3
        from moto import mock_aws

        monkeypatch.setattr("app.config.settings.storage_backend", "s3")
        monkeypatch.setattr("app.config.settings.storage_s3_bucket", "my-bucket")
        monkeypatch.setattr("app.config.settings.storage_s3_region", "us-east-1")

        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="my-bucket")
            from app.services.storage import get_storage_backend, S3Storage
            backend = get_storage_backend()
            assert isinstance(backend, S3Storage)

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.storage_backend", "gcs")
        from app.services.storage import get_storage_backend
        with pytest.raises(ValueError, match="STORAGE_BACKEND"):
            get_storage_backend()
