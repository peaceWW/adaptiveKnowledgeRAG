"""把已入库的图/公式/章节单元按第二期规则回写文本、主题、Fig/Eq 概念与互指关系。"""
from __future__ import annotations

from typing import Any

from app.ingestion.figure_equation_bundle import (
    fig_eq_concepts,
    figure_content,
    figure_equation_pairs,
    infer_engineering_topic,
    merge_concepts,
)


def apply_bundle_to_units(units: list[Any], structure: dict[str, Any] | None, paper_title: str = "") -> list[Any]:
    """原地更新 KnowledgeUnit：图补 engineering_topic 与 embedding 正文，章节 concepts 带 Fig/Eq。"""
    structure = structure or {}
    for unit in units:
        meta = dict(getattr(unit, "unit_meta", None) or {})
        kind = str(meta.get("kind") or "")
        if kind == "figure":
            fig_id = str(meta.get("fig_id") or "")
            caption = str(meta.get("caption") or unit.source_span or "")
            topic = infer_engineering_topic(
                caption,
                unit.content,
                " ".join(str(item) for item in (meta.get("components") or [])),
                paper_title,
                suggested=str(meta.get("engineering_topic") or ""),
            )
            if topic:
                meta["engineering_topic"] = topic
            unit.content = figure_content(
                fig_id,
                caption,
                figure_type=str(meta.get("figure_type") or ""),
                components=meta.get("components") or [],
                parameters=meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {},
                description=_description_from_content(unit.content),
                engineering_topic=topic,
            )
            unit.concepts = merge_concepts(unit.concepts, [f"Fig.{fig_id}", topic])
            unit.unit_meta = meta
        elif kind == "equation":
            eq_id = str(meta.get("eq_id") or "")
            unit.concepts = merge_concepts(unit.concepts, [f"Eq.({eq_id})"])
        elif kind in {"concept", "section"}:
            section_anchor = str(meta.get("parent_anchor") or meta.get("anchor") or "")
            unit.concepts = merge_concepts(
                unit.concepts,
                fig_eq_concepts(unit.content or "", structure, section_anchor),
            )
    return units


def unit_figure_equation_pairs(units: list[Any]) -> list[tuple[str, str]]:
    """从已入库单元收集应写入 HAS_EQUATION / HAS_FIGURE 的锚点对。"""
    figures = []
    equations = []
    for unit in units:
        meta = getattr(unit, "unit_meta", None) or {}
        kind = str(meta.get("kind") or "")
        if kind == "figure":
            figures.append(
                {
                    "fig_id": meta.get("fig_id"),
                    "caption": meta.get("caption") or "",
                    "content": unit.content,
                    "page": unit.source_page,
                    "source_page": unit.source_page,
                }
            )
        elif kind == "equation":
            equations.append(
                {
                    "eq_id": meta.get("eq_id"),
                    "nearby_text": unit.source_span or "",
                    "content": unit.content,
                    "page": unit.source_page,
                    "source_page": unit.source_page,
                }
            )
    return figure_equation_pairs(figures, equations)


def _description_from_content(content: str) -> str:
    text = str(content or "")
    marker = "Description: "
    if marker in text:
        return text.split(marker, 1)[-1].strip()
    return ""
