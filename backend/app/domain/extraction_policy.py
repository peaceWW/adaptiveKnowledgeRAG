"""Shared contract for strategy configuration, ingestion and review categories."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: bool = True
    formulas: bool = True
    images: bool = True
    tables: bool = True
    references: bool = True
    chunk_size: int = Field(1200, ge=200, le=12000)
    chunk_overlap: int = Field(100, ge=0, le=2000)
    formula_mode: Literal["source", "vision"] = "source"
    image_mode: Literal["source", "vision"] = "source"
    table_mode: Literal["source", "vision"] = "source"

    @model_validator(mode="after")
    def validate_policy(self):
        if not any((self.text, self.formulas, self.images, self.tables, self.references)):
            raise ValueError("请至少启用一种提取内容")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("重叠长度必须小于分段长度")
        return self


EXTRACTION_KINDS = [
    {"key": "text", "policy_key": "text", "label": "提取文本"},
    {"key": "equation", "policy_key": "formulas", "label": "提取公式"},
    {"key": "figure", "policy_key": "images", "label": "提取图片"},
    {"key": "table", "policy_key": "tables", "label": "提取表格"},
    {"key": "citation", "policy_key": "references", "label": "参考文献"},
]


def extraction_kind(unit) -> str:
    meta = (unit.get("unit_meta") if isinstance(unit, dict) else unit.unit_meta) or {}
    role = unit.get("semantic_role") if isinstance(unit, dict) else unit.semantic_role
    kind = meta.get("kind")
    if kind in {"equation", "figure", "table", "citation"}:
        return kind
    # Earlier records used semantic roles without an inventory kind.
    if role == "formula":
        return "equation"
    if role == "reference":
        return "citation"
    return "text"


def normalized_policy(value: dict | None) -> dict:
    return ExtractionPolicy.model_validate(value or {}).model_dump()
