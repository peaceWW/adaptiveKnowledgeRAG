from __future__ import annotations

import io
import logging
import socket

from minio import Minio

from app.config import get_settings

logger = logging.getLogger(__name__)


def _reachable(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class MinioStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket
        self.available = False
        self._local: dict[str, bytes] = {}
        host, _, port = settings.minio_endpoint.partition(":")
        if not _reachable(host or "localhost", int(port or 9000)):
            logger.warning("MinIO unreachable, using local fallback")
            self.client = None
            return
        try:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self.available = True
        except Exception as exc:
            logger.warning("MinIO unavailable, using local fallback: %s", exc)
            self.client = None

    def put(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self.client:
            self.client.put_object(
                self.bucket,
                object_key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        else:
            self._local[object_key] = data
        return object_key

    def get(self, object_key: str) -> bytes:
        if self.client:
            response = self.client.get_object(self.bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        return self._local.get(object_key, b"")
