# 提示词单一入口：YAML 为出厂默认，模型中心保存后覆盖运行时缓存。
from __future__ import annotations

from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
_overrides: dict[str, str] = {}


def apply_prompt_override(prompt_id: str, content: str) -> None:
    """模型中心保存或启动同步后立即生效，无需等下次读盘。"""
    if prompt_id:
        _overrides[prompt_id] = content or ""


def load_prompt(prompt_id: str, default: str = "") -> str:
    """优先用模型中心覆盖，否则读 backend/prompts/{id}.yaml。"""
    cached = _overrides.get(prompt_id)
    if cached and cached.strip():
        return cached
    path = PROMPT_DIR / f"{prompt_id}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        content = str(data.get("content") or "")
        if content.strip():
            return content
    except Exception:
        pass
    return default


def iter_prompt_files() -> list[dict]:
    """扫描 YAML，供启动时写入 prompt_template 表。"""
    rows: list[dict] = []
    for path in sorted(PROMPT_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prompt_id = str(data.get("prompt_id") or path.stem)
        rows.append(
            {
                "prompt_id": prompt_id,
                "version": str(data.get("version") or "V1"),
                "strategy": str(data.get("strategy") or ""),
                "model": str(data.get("model") or "default"),
                "temperature": float(data.get("temperature") or 0.0),
                "content": str(data.get("content") or ""),
                "title": str(data.get("title") or prompt_id),
                "input_schema": data.get("input_schema") or {},
                "output_schema": data.get("output_schema") or {},
            }
        )
    return rows


def prompt_catalog() -> dict[str, dict]:
    return {row["prompt_id"]: row for row in iter_prompt_files()}
