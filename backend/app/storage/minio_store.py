from __future__ import annotations

import io
import logging
import os
import shutil
import socket
from pathlib import Path

from minio import Minio

from app.config import get_settings

logger = logging.getLogger(__name__)


def _os_file(path: Path) -> Path:
    """Windows 默认 MAX_PATH=260，超长路径会以 FileNotFoundError 出现；加 \\\\?\\ 走长路径 API。"""
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def _reachable(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host or "localhost", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class MinioStore:
    """对象存储入口：始终落盘到 STORAGE_DIR，MinIO 可用时再多写一份。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket
        self.root = settings.storage_root
        self.root.mkdir(parents=True, exist_ok=True)
        self.available = False
        self.client: Minio | None = None
        host, _, port = settings.minio_endpoint.partition(":")
        if not _reachable(host or "localhost", int(port or 9000)):
            logger.warning("MinIO unreachable, using disk store at %s", self.root)
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
            logger.warning("MinIO unavailable, using disk store at %s: %s", self.root, exc)
            self.client = None

    def disk_path(self, object_key: str) -> Path:
        """object_key 映射到 STORAGE_DIR 下的真实文件，禁止跳出根目录。"""
        relative = Path(str(object_key or "").replace("\\", "/").lstrip("/"))
        path = (self.root / relative).resolve()
        path.relative_to(self.root)
        return path

    def put(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = _os_file(self.disk_path(object_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data or b"")
        if self.client:
            try:
                self.client.put_object(
                    self.bucket,
                    object_key,
                    io.BytesIO(data or b""),
                    length=len(data or b""),
                    content_type=content_type,
                )
            except Exception as exc:
                logger.warning("MinIO put failed, disk copy kept: %s", exc)
        return object_key

    def get(self, object_key: str) -> bytes:
        if not object_key:
            return b""
        path = _os_file(self.disk_path(object_key))
        if path.is_file():
            return path.read_bytes()
        if self.client:
            try:
                response = self.client.get_object(self.bucket, object_key)
                try:
                    data = response.read()
                finally:
                    response.close()
                    response.release_conn()
                if data:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                return data or b""
            except Exception as exc:
                logger.warning("MinIO get failed: %s", exc)
        return b""

    def delete(self, object_key: str) -> None:
        path = _os_file(self.disk_path(object_key))
        if path.is_file():
            path.unlink()
        if self.client:
            try:
                self.client.remove_object(self.bucket, object_key)
            except Exception as exc:
                logger.warning("MinIO delete failed: %s", exc)

    def delete_prefix(self, prefix: str) -> None:
        """删除某文档的原文或截图目录。"""
        if not prefix:
            return
        folder = _os_file(self.disk_path(prefix))
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        elif folder.is_file():
            folder.unlink(missing_ok=True)
        if self.client:
            try:
                for obj in self.client.list_objects(self.bucket, prefix=prefix, recursive=True):
                    self.client.remove_object(self.bucket, obj.object_name)
            except Exception as exc:
                logger.warning("MinIO prefix delete failed: %s", exc)
