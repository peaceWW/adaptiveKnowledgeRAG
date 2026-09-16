# 原文/截图必须落盘：新 Store 实例仍能读到，问答才能拿到 image_url。
from __future__ import annotations

import pytest

from app.config import get_settings
from app.storage.minio_store import MinioStore
from app.storage.paths import asset_key_allowed, attach_image_refs, image_refs, original_object_key, public_asset_url


def test_original_and_image_paths():
    key = original_object_key("kb1", "doc1", "../a/paper.pdf")
    assert key == "originals/kb1/doc1/original.pdf"
    long_name = (
        "A_10_Gb_s_Hybrid_ADC-Based_Receiver_With_Embedded_Analog_and_Per-Symbol_"
        "Dynamically_Enabled_Digital_Equalization_1_15_cn.pdf"
    )
    long_key = original_object_key("kb1", "doc1", long_name)
    assert long_key == "originals/kb1/doc1/original.pdf"
    assert len(long_key) < 80
    refs = image_refs("doc1", "images/doc1/fig_1.png")
    assert refs["image_key"] == "images/doc1/fig_1.png"
    assert refs["image_url"] == public_asset_url("doc1", "images/doc1/fig_1.png")
    assert "key=images" in refs["image_url"]
    meta = attach_image_refs("doc1", {"image_key": "images/doc1/fig_1.png", "kind": "figure"})
    assert meta["image_url"].startswith("/api/documents/doc1/assets?key=")
    assert asset_key_allowed("doc1", "images/doc1/fig_1.png")
    assert asset_key_allowed("doc1", "docs/doc1/fig/1.png")
    assert not asset_key_allowed("doc1", "images/other/fig.png")
    assert not asset_key_allowed("doc1", "images/doc1/../secret.png")


def test_disk_survives_new_store(tmp_path, monkeypatch):
    """模拟重启：关掉旧 MinioStore 后再 new 一个，磁盘上的原文和 PNG 还在。"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        first = MinioStore()
        first.put("originals/kb/doc1/paper.pdf", b"pdf-bytes", "application/pdf")
        first.put("images/doc1/fig_1.png", b"png-bytes", "image/png")
        first.available = False
        first.client = None
        get_settings.cache_clear()
        restarted = MinioStore()
        restarted.available = False
        restarted.client = None
        assert restarted.get("originals/kb/doc1/paper.pdf") == b"pdf-bytes"
        assert restarted.get("images/doc1/fig_1.png") == b"png-bytes"
        restarted.delete_prefix("images/doc1")
        assert restarted.get("images/doc1/fig_1.png") == b""
        assert restarted.get("originals/kb/doc1/paper.pdf") == b"pdf-bytes"
    finally:
        get_settings.cache_clear()


def test_put_long_ieee_filename_on_deep_root(tmp_path, monkeypatch):
    """复现上传 IEEE 长文件名：目录已经很深时，短 object_key 与 \\\\?\\ 都能写成功。"""
    deep = tmp_path / ("seg" * 20) / ("seg" * 20)
    monkeypatch.setenv("STORAGE_DIR", str(deep))
    get_settings.cache_clear()
    try:
        store = MinioStore()
        store.available = False
        store.client = None
        ieee = (
            "A_10_Gb_s_Hybrid_ADC-Based_Receiver_With_Embedded_Analog_and_Per-Symbol_"
            "Dynamically_Enabled_Digital_Equalization_1_15_cn.pdf"
        )
        key = original_object_key(
            "95d28d3c-4f28-4ca9-b698-83b13b5f92f2",
            "ad4c3b61-55ee-48f0-80f1-64f50d0432b7",
            ieee,
        )
        store.put(key, b"%PDF-short-key")
        assert store.get(key) == b"%PDF-short-key"
        legacy = (
            "originals/95d28d3c-4f28-4ca9-b698-83b13b5f92f2/"
            f"ad4c3b61-55ee-48f0-80f1-64f50d0432b7/{ieee}"
        )
        store.put(legacy, b"%PDF-legacy")
        assert store.get(legacy) == b"%PDF-legacy"
    finally:
        get_settings.cache_clear()


def test_disk_path_stays_inside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        store = MinioStore()
        with pytest.raises(ValueError):
            store.disk_path("../outside.bin")
    finally:
        get_settings.cache_clear()
