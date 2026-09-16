from __future__ import annotations

import json
import re
from typing import Any, Iterable

from app.domain.enums import KnowledgeType, SemanticRole, SourceLevel
from app.domain.strategy import DocumentContext, KnowledgeUnitDraft
from app.ingestion.academic_parse import render_region_png
from app.ingestion.extractor import _extract_concepts, _infer_role, _split_blocks
from app.ingestion.figure_equation_bundle import (
    FIG_REF_RE,
    equation_content,
    fig_eq_concepts,
    figure_content,
    figure_equation_pairs,
    infer_engineering_topic,
    merge_concepts,
)
from app.observability.pipeline_log import draft_digest, step as pipeline_step
from app.prompts.loader import load_prompt
from app.storage.paths import image_refs

DEFAULT_PROMPT = """你是芯片设计工程师，从章节原文抽取可检索的设计知识点。不得补原文没有的工艺或指标。必须输出 JSON：
{"units":[{"title":"","semantic_role":"principle","content":"","concepts":[],"importance":"core","source_page":1,"relations":[],"unit_meta":{}}]}
"""
DEFAULT_FIGURE_PROMPT = """你是芯片设计工程师，只描述图中可见内容。输出 JSON：
{"figure_type":"","description":"","components":[],"parameters":{},"engineering_topic":""}
不得编造未标出的参数。
"""
PAPER_ROLES = {
    SemanticRole.DEFINITION,
    SemanticRole.EXPLANATION,
    SemanticRole.PRINCIPLE,
    SemanticRole.FORMULA,
    SemanticRole.PARAMETER,
    SemanticRole.CONSTRAINT,
    SemanticRole.RULE,
    SemanticRole.EXAMPLE,
    SemanticRole.EXCEPTION,
    SemanticRole.REFERENCE,
    SemanticRole.METRIC,
    SemanticRole.COMPARISON,
    SemanticRole.LIMITATION,
    SemanticRole.INTERFACE,
    SemanticRole.SUMMARY,
    SemanticRole.BACKGROUND,
}

SECTION_ROLE_HINTS = (
    ("result", SemanticRole.METRIC),
    ("measurement", SemanticRole.METRIC),
    ("experimental", SemanticRole.METRIC),
    ("architecture", SemanticRole.PRINCIPLE),
    ("circuit", SemanticRole.INTERFACE),
    ("implementation", SemanticRole.INTERFACE),
    ("conclusion", SemanticRole.SUMMARY),
    ("introduction", SemanticRole.BACKGROUND),
    ("abstract", SemanticRole.SUMMARY),
)


def extract_paper_units(
    context: DocumentContext,
    allowed_roles: Iterable[SemanticRole] | None = None,
    knowledge_type: KnowledgeType = KnowledgeType.TECHNICAL_CONCEPT,
) -> list[KnowledgeUnitDraft]:
    allowed = set(allowed_roles or PAPER_ROLES)
    drafts: list[KnowledgeUnitDraft] = []
    if context.extraction_policy.get("text", True):
        drafts.extend(_metadata_units(context, knowledge_type, allowed))
        drafts.extend(_section_units(context, knowledge_type, allowed))
        drafts.extend(_parameter_units(context, knowledge_type, allowed))
    drafts.extend(_inventory_units(context, knowledge_type, allowed))
    llm_units = _llm_section_units(context, knowledge_type, allowed) if context.extraction_policy.get("text", True) else []
    drafts.extend(llm_units)
    semantic_source = "llm_section"
    if not llm_units and context.extraction_policy.get("text", True):
        drafts.extend(_heuristic_section_units(context, knowledge_type, allowed))
        semantic_source = "heuristic_section"
    unique = _dedupe_drafts(drafts)
    _bind_figure_equations(unique, context)
    pipeline_step(
        "ingest",
        "chunk",
        inputs={
            "filename": context.filename,
            "rule": "paper: metadata+section_canonical+inventory+per_section_semantic",
            "section_count": len((context.structure or {}).get("sections") or []),
            "figure_count": len((context.structure or {}).get("figures") or []),
            "equation_count": len((context.structure or {}).get("equations") or []),
            "has_model_key": bool(getattr(getattr(context, "gateway", None), "client", None)),
        },
        result={**draft_digest(unique), "semantic_source": semantic_source},
    )
    return unique


def _load_prompt() -> str:
    return load_prompt("technical-extractor", DEFAULT_PROMPT)


def _metadata_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    meta = (context.structure or {}).get("metadata") or {}
    keywords = meta.get("keywords") or []
    authors = meta.get("authors") or []
    content_parts = [
        meta.get("title") or context.filename,
        f"Authors: {', '.join(authors)}" if authors else "",
        f"Venue: {meta.get('venue')}" if meta.get("venue") else "",
        f"Year: {meta.get('year')}" if meta.get("year") else "",
        f"DOI: {meta.get('doi')}" if meta.get("doi") else "",
        f"Keywords: {', '.join(keywords)}" if keywords else "",
    ]
    content = "\n".join(part for part in content_parts if part)
    role = SemanticRole.SUMMARY if SemanticRole.SUMMARY in allowed else SemanticRole.DEFINITION
    return [
        KnowledgeUnitDraft(
            title=(meta.get("title") or "Paper metadata")[:180],
            content=content,
            semantic_role=role,
            knowledge_type=knowledge_type,
            importance="core",
            concepts=list(keywords)[:8],
            source_span=content[:500],
            source_chapter="front",
            source_section="metadata",
            source_page=1,
            parent_context=context.filename,
            confidence=0.95,
            unit_meta={"anchor": "meta:paper", "kind": "metadata", "doi": meta.get("doi"), "venue": meta.get("venue")},
            source_level=SourceLevel.OFFICIAL.value,
        )
    ]


def _parameter_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    if SemanticRole.PARAMETER not in allowed:
        return []
    meta = (context.structure or {}).get("metadata") or {}
    keywords = [str(item) for item in (meta.get("keywords") or []) if item]
    index_text = ""
    for section in (context.structure or {}).get("sections") or []:
        if str(section.get("id") or "").lower() in {"keywords", "index terms"}:
            index_text = section.get("text") or ""
    if not keywords and not index_text:
        return []
    content = "Index Terms / keywords: " + ", ".join(keywords)
    if index_text:
        content = f"{content}\n{index_text}".strip()
    return [
        KnowledgeUnitDraft(
            title="Paper index terms",
            content=content,
            semantic_role=SemanticRole.PARAMETER,
            knowledge_type=knowledge_type,
            importance="supporting",
            concepts=(keywords or _extract_concepts(content))[:8],
            source_span=content[:500],
            source_chapter="keywords",
            source_section="index-terms",
            source_page=1,
            parent_context=context.filename,
            confidence=0.9,
            unit_meta={"anchor": "param:keywords", "kind": "parameter", "parent_anchor": "sec:keywords"},
            source_level=SourceLevel.OFFICIAL.value,
        )
    ]


def _section_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    drafts: list[KnowledgeUnitDraft] = []
    for section in (context.structure or {}).get("sections") or []:
        section_id = str(section.get("id") or "")
        if not section_id:
            continue
        text = (section.get("text") or "").strip()
        if len(text) < 8 and not section.get("title"):
            continue
        title = f"{section_id} {section.get('title', '')}".strip()
        role = _section_default_role(section, allowed)
        drafts.append(
            KnowledgeUnitDraft(
                title=title[:180],
                content=text or title,
                semantic_role=role,
                knowledge_type=knowledge_type,
                importance="core" if role in {SemanticRole.PRINCIPLE, SemanticRole.SUMMARY, SemanticRole.METRIC} else "supporting",
                concepts=merge_concepts(_extract_concepts(text or title), fig_eq_concepts(text or title, context.structure, f"sec:{section_id}")),
                source_span=text[:500],
                source_chapter=section_id[:64],
                source_section=str(section.get("title") or "")[:80],
                source_page=int(section.get("page") or 1),
                parent_context=f"{context.filename} / {title}",
                confidence=0.86,
                relations=_body_relations(text),
                unit_meta={"anchor": f"sec:{section_id}", "kind": "section", "section_id": section_id},
                source_level=SourceLevel.REVIEWED.value,
            )
        )
    return drafts


def _inventory_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    """公式/图/表/引用只看 extraction_policy，不要求用户勾选对应文本 Role。"""
    structure = context.structure or {}
    policy = context.extraction_policy or {}
    drafts: list[KnowledgeUnitDraft] = []
    if policy.get("formulas", True):
        for eq in structure.get("equations") or []:
            drafts.append(_equation_unit(context, eq, knowledge_type))
    if policy.get("references", True):
        for cite in structure.get("citations") or []:
            drafts.append(_citation_unit(context, cite, knowledge_type))
    if policy.get("tables", True):
        table_role = SemanticRole.METRIC if (not allowed or SemanticRole.METRIC in allowed) else SemanticRole.PARAMETER
        for table in structure.get("tables") or []:
            drafts.append(_table_unit(context, table, knowledge_type, table_role))
    if policy.get("images", True):
        fig_role = SemanticRole.INTERFACE if (not allowed or SemanticRole.INTERFACE in allowed) else SemanticRole.EXPLANATION
        for fig in structure.get("figures") or []:
            drafts.append(_figure_unit(context, fig, knowledge_type, fig_role))
    return drafts


def _equation_unit(context: DocumentContext, eq: dict[str, Any], knowledge_type: KnowledgeType) -> KnowledgeUnitDraft:
    eq_id = str(eq.get("eq_id") or "")
    latex = str(eq.get("latex") or "")
    raw = str(eq.get("raw") or "")
    if not latex and context.extraction_policy.get("formula_mode", "source") == "vision":
        vision = _maybe_vision_latex(context, eq)
        latex = str(vision.get("latex") or "")
        if latex:
            eq["latex"] = latex
        if vision.get("meaning"):
            eq["meaning"] = vision.get("meaning")
        if vision.get("variables"):
            eq["variables"] = vision.get("variables")
    nearby = str(eq.get("nearby_text") or "")
    meaning = str(eq.get("meaning") or "")
    variables = eq.get("variables") or {}
    body = equation_content(
        eq_id,
        latex=latex,
        raw=raw,
        nearby=nearby,
        meaning=meaning,
        variables=variables if isinstance(variables, dict) else {},
    )
    parent_anchor = _parent_anchor_for_inventory(context.structure, "eq", eq_id, int(eq.get("page") or 1))
    return KnowledgeUnitDraft(
        title=f"Equation ({eq_id})",
        content=body,
        semantic_role=SemanticRole.FORMULA,
        knowledge_type=knowledge_type,
        importance="core",
        concepts=merge_concepts(_extract_concepts(body), [f"Eq.({eq_id})"]),
        source_span=(nearby or raw)[:500],
        source_chapter=_section_for_page(context.structure, int(eq.get("page") or 1)),
        source_section=f"eq:{eq_id}",
        source_page=int(eq.get("page") or 1),
        parent_context=context.filename,
        confidence=0.9 if latex else 0.55,
        relations=[{"type": "BELONGS_TO", "to_key": parent_anchor}] if parent_anchor else [],
        unit_meta={
            "anchor": f"eq:{eq_id}",
            "kind": "equation",
            "eq_id": eq_id,
            "latex": latex,
            "bbox": eq.get("bbox") or [],
            **image_refs(context.document_id, eq.get("image_key") or ""),
            "meaning": meaning,
            "variables": variables,
            "parent_anchor": parent_anchor,
        },
        source_level=SourceLevel.REVIEWED.value if latex else SourceLevel.AI_GENERATED.value,
    )


def _citation_unit(context: DocumentContext, cite: dict[str, Any], knowledge_type: KnowledgeType) -> KnowledgeUnitDraft:
    key = str(cite.get("key") or "")
    text = str(cite.get("text") or "").strip() or f"Citation {key} (in-text reference)"
    cited_in = cite.get("cited_in_sections") or []
    relations = [{"type": "BELONGS_TO", "to_key": "sec:references"}]
    return KnowledgeUnitDraft(
        title=f"Reference {key}",
        content=text,
        semantic_role=SemanticRole.REFERENCE,
        knowledge_type=knowledge_type,
        importance="supporting",
        concepts=_extract_concepts(text),
        source_span=text[:500],
        source_chapter="references",
        source_section=key,
        source_page=_page_of_section(context.structure, "references"),
        parent_context=context.filename,
        confidence=0.92 if cite.get("text") else 0.6,
        relations=relations,
        unit_meta={"anchor": f"cite:{key}", "kind": "citation", "cite_key": key, "cited_in_sections": cited_in, "parent_anchor": "sec:references"},
        source_level=SourceLevel.OFFICIAL.value,
    )


def _table_unit(
    context: DocumentContext, table: dict[str, Any], knowledge_type: KnowledgeType, role: SemanticRole
) -> KnowledgeUnitDraft:
    table_id = str(table.get("table_id") or "")
    caption = str(table.get("caption") or "")
    rows = table.get("rows") or []
    rendered = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
    content = f"TABLE {table_id}. {caption}\n{rendered}".strip()
    parent_anchor = _parent_anchor_for_inventory(context.structure, "table", table_id, int(table.get("page") or 1))
    return KnowledgeUnitDraft(
        title=f"TABLE {table_id}" + (f" {caption}" if caption else ""),
        content=content,
        semantic_role=role,
        knowledge_type=knowledge_type,
        importance="core",
        concepts=_extract_concepts(content),
        source_span=caption[:500] or content[:500],
        source_chapter=_section_for_page(context.structure, int(table.get("page") or 1)),
        source_section=f"table:{table_id}",
        source_page=int(table.get("page") or 1),
        parent_context=context.filename,
        confidence=0.88 if rows else 0.7,
        relations=[{"type": "BELONGS_TO", "to_key": parent_anchor}] if parent_anchor else [],
        unit_meta={"anchor": f"table:{table_id}", "kind": "table", "table_id": table_id, "rows": rows, "caption": caption,
                   **image_refs(context.document_id, table.get("image_key") or ""), "bbox": table.get("bbox") or [], "parent_anchor": parent_anchor,
                   "recognition_status": "unavailable" if context.extraction_policy.get("table_mode", "source") == "vision" else "source"},
        source_level=SourceLevel.REVIEWED.value,
    )


def _figure_unit(
    context: DocumentContext, fig: dict[str, Any], knowledge_type: KnowledgeType, role: SemanticRole
) -> KnowledgeUnitDraft:
    fig_id = str(fig.get("fig_id") or "")
    caption = str(fig.get("caption") or "")
    vision = _maybe_vision_figure(context, fig) if context.extraction_policy.get("image_mode", "source") == "vision" else {}
    description = str(vision.get("description") or "")
    figure_type = str(vision.get("figure_type") or "")
    components = vision.get("components") or []
    parameters = vision.get("parameters") or {}
    paper_title = str(((context.structure or {}).get("metadata") or {}).get("title") or context.filename)
    engineering_topic = infer_engineering_topic(
        caption,
        description,
        " ".join(str(item) for item in components),
        paper_title,
        suggested=str(vision.get("engineering_topic") or ""),
    )
    content = figure_content(
        fig_id,
        caption,
        figure_type=figure_type,
        components=components,
        parameters=parameters if isinstance(parameters, dict) else {},
        description=description,
        engineering_topic=engineering_topic,
    )
    parent_anchor = _parent_anchor_for_inventory(context.structure, "fig", fig_id, int(fig.get("page") or 1))
    relations = [{"type": "BELONGS_TO", "to_key": parent_anchor}] if parent_anchor else []
    if parent_anchor:
        relations.append({"type": "ILLUSTRATES", "to_key": parent_anchor})
    return KnowledgeUnitDraft(
        title=f"Fig. {fig_id}",
        content=content,
        semantic_role=role,
        knowledge_type=knowledge_type,
        importance="supporting",
        concepts=merge_concepts(_extract_concepts(content), [f"Fig.{fig_id}", engineering_topic]),
        source_span=caption[:500],
        source_chapter=_section_for_page(context.structure, int(fig.get("page") or 1)),
        source_section=f"fig:{fig_id}",
        source_page=int(fig.get("page") or 1),
        parent_context=context.filename,
        confidence=0.8 if description else 0.72,
        relations=relations,
        unit_meta={
            "anchor": f"fig:{fig_id}",
            "kind": "figure",
            "fig_id": fig_id,
            "caption": caption,
            "source_url": fig.get("source_url") or "",
            "asset_status": fig.get("asset_status") or ("available" if fig.get("image_key") else "missing"),
            **image_refs(context.document_id, fig.get("image_key") or ""),
            "bbox": fig.get("bbox") or [],
            "crop_mode": fig.get("crop_mode") or "",
            "figure_type": figure_type,
            "components": components,
            "parameters": parameters,
            "engineering_topic": engineering_topic,
            "parent_anchor": parent_anchor,
        },
        source_level=SourceLevel.AI_GENERATED.value if description else SourceLevel.REVIEWED.value,
    )


def _llm_section_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    gateway = context.gateway
    if gateway is None or not getattr(gateway, "client", None):
        return []
    sections = [
        section
        for section in (context.structure or {}).get("sections") or []
        if not str(section.get("id") or "").lower().startswith("reference")
    ]
    if not sections:
        return []
    prompt = _load_prompt()
    drafts: list[KnowledgeUnitDraft] = []
    for section in sections:
        payload = {
            "section_id": section.get("id"),
            "section_title": section.get("title"),
            "page": section.get("page"),
            "text": (section.get("text") or "")[:6000],
            "equations": [
                item.get("eq_id")
                for item in (context.structure or {}).get("equations") or []
                if int(item.get("page") or 0) >= int(section.get("page") or 0)
            ][:12],
            "citation_keys": re.findall(r"\[\d+\]", section.get("text") or ""),
        }
        result = gateway.chat_json(prompt, json.dumps(payload, ensure_ascii=False), temperature=0.0)
        for item in result.get("units") or []:
            draft = _unit_from_llm_item(item, section, context, knowledge_type, allowed)
            if draft:
                drafts.append(draft)
    return drafts


def _heuristic_section_units(
    context: DocumentContext, knowledge_type: KnowledgeType, allowed: set[SemanticRole]
) -> list[KnowledgeUnitDraft]:
    sections = (context.structure or {}).get("sections") or []
    drafts: list[KnowledgeUnitDraft] = []
    for section in sections:
        if str(section.get("id") or "").lower().startswith("reference"):
            continue
        text = (section.get("text") or "").strip()
        if len(text) < 40:
            continue
        role = _section_default_role(section, allowed)
        title = f"{section.get('id', '')} {section.get('title', '')}".strip()
        blocks, _rule = _split_blocks(text)
        chosen = blocks if blocks else [text]
        for block in chosen:
            inferred = _infer_role(block, allowed)
            use_role = inferred if inferred in allowed else role
            drafts.append(
                KnowledgeUnitDraft(
                    title=(title or _first_sentence(block))[:180],
                    content=block.strip(),
                    semantic_role=use_role,
                    knowledge_type=knowledge_type,
                    importance="core" if use_role in {SemanticRole.PRINCIPLE, SemanticRole.SUMMARY, SemanticRole.METRIC} else "supporting",
                    concepts=merge_concepts(
                        _extract_concepts(block),
                        fig_eq_concepts(block, context.structure, f"sec:{section.get('id')}"),
                    ),
                    source_span=block[:500],
                    source_chapter=str(section.get("id") or ""),
                    source_section=str(section.get("title") or "")[:80],
                    source_page=int(section.get("page") or 1),
                    parent_context=f"{context.filename} / {title}",
                    confidence=0.74,
                    relations=_body_relations(block) + ([{"type": "BELONGS_TO", "to_key": f"sec:{section.get('id')}"}] if section.get("id") else []),
                    unit_meta={"anchor": f"sec:{section.get('id')}:{len(drafts)}", "kind": "concept", "parent_anchor": f"sec:{section.get('id')}"},
                )
            )
    return drafts


def _unit_from_llm_item(
    item: dict[str, Any],
    section: dict[str, Any],
    context: DocumentContext,
    knowledge_type: KnowledgeType,
    allowed: set[SemanticRole],
) -> KnowledgeUnitDraft | None:
    content = str(item.get("content") or "").strip()
    if len(content) < 20:
        return None
    role_key = str(item.get("semantic_role") or "principle")
    try:
        role = SemanticRole(role_key)
    except ValueError:
        role = _section_default_role(section, allowed)
    if role not in allowed:
        role = next(iter(allowed), SemanticRole.PRINCIPLE)
    if role in {SemanticRole.FORMULA, SemanticRole.REFERENCE}:
        return None
    title = str(item.get("title") or section.get("title") or role.value)
    parent_anchor = f"sec:{section.get('id')}" if section.get("id") else ""
    relations = _filter_known_relations(list(item.get("relations") or []) + _body_relations(content), context)
    if parent_anchor:
        relations.append({"type": "BELONGS_TO", "to_key": parent_anchor})
    return KnowledgeUnitDraft(
        title=title[:180],
        content=content,
        semantic_role=role,
        knowledge_type=knowledge_type,
        importance=str(item.get("importance") or "core"),
        concepts=merge_concepts(
            list(item.get("concepts") or _extract_concepts(content)),
            fig_eq_concepts(content, context.structure, parent_anchor),
        )[:12],
        source_span=content[:500],
        source_chapter=str(section.get("id") or ""),
        source_section=str(section.get("title") or "")[:80],
        source_page=int(item.get("source_page") or section.get("page") or 1),
        parent_context=f"{context.filename} / {section.get('title')}",
        confidence=0.82,
        relations=relations,
        unit_meta={"kind": "concept", "section_id": section.get("id"), "parent_anchor": parent_anchor, **(item.get("unit_meta") or {})},
    )


def _maybe_vision_latex(context: DocumentContext, eq: dict[str, Any]) -> dict[str, Any]:
    gateway = context.gateway
    bbox = eq.get("bbox") or []
    if not context.raw or not bbox or gateway is None or not getattr(gateway, "client", None):
        return {}
    try:
        png = render_region_png(context.raw, int(eq.get("page") or 1), [float(v) for v in bbox])
        if not png:
            return {}
        result = gateway.chat_vision_json(
            "Convert the equation image to LaTeX and explain symbols. Return JSON {\"latex\":\"\",\"meaning\":\"\",\"variables\":{}}. Do not invent symbols that are not visible.",
            f"Equation ({eq.get('eq_id')})",
            png,
        )
        return {
            "latex": str(result.get("latex") or "").strip(),
            "meaning": str(result.get("meaning") or "").strip(),
            "variables": result.get("variables") or {},
        }
    except Exception:
        return {}


def _maybe_vision_figure(context: DocumentContext, fig: dict[str, Any]) -> dict[str, Any]:
    gateway = context.gateway
    if gateway is None or not getattr(gateway, "client", None):
        return {}
    png = b""
    image_key = str(fig.get("image_key") or "")
    if image_key and context.minio is not None:
        try:
            png = context.minio.get(image_key) or b""
        except Exception:
            png = b""
    if not png and context.raw and fig.get("bbox"):
        png = render_region_png(context.raw, int(fig.get("page") or 1), [float(v) for v in fig.get("bbox") or []])
    if not png:
        return {}
    prompt = _load_figure_prompt()
    try:
        result = gateway.chat_vision_json(
            prompt,
            f"Caption: Fig. {fig.get('fig_id')}. {fig.get('caption') or ''}",
            png,
        )
        return {
            "description": str(result.get("description") or "").strip(),
            "figure_type": str(result.get("figure_type") or "").strip(),
            "components": result.get("components") or [],
            "parameters": result.get("parameters") or {},
            "engineering_topic": str(result.get("engineering_topic") or "").strip(),
        }
    except Exception:
        return {}


def _bind_figure_equations(drafts: list[KnowledgeUnitDraft], context: DocumentContext) -> None:
    """同页或 caption 互指时补 HAS_EQUATION / HAS_FIGURE；章节单元补 Fig/Eq 概念。"""
    figures = []
    equations = []
    for draft in drafts:
        meta = draft.unit_meta or {}
        kind = str(meta.get("kind") or "")
        if kind == "figure":
            figures.append(
                {
                    "fig_id": meta.get("fig_id"),
                    "caption": meta.get("caption") or "",
                    "content": draft.content,
                    "page": draft.source_page,
                    "source_page": draft.source_page,
                }
            )
        elif kind == "equation":
            equations.append(
                {
                    "eq_id": meta.get("eq_id"),
                    "nearby_text": draft.source_span or "",
                    "content": draft.content,
                    "page": draft.source_page,
                    "source_page": draft.source_page,
                }
            )
    pair_keys = {(f"fig:{fig_id}", f"eq:{eq_id}") for fig_id, eq_id in figure_equation_pairs(figures, equations)}
    by_anchor = {str((draft.unit_meta or {}).get("anchor") or ""): draft for draft in drafts}
    for fig_key, eq_key in pair_keys:
        fig_draft = by_anchor.get(fig_key)
        eq_draft = by_anchor.get(eq_key)
        if not fig_draft or not eq_draft:
            continue
        fig_draft.relations = list(fig_draft.relations or []) + [{"type": "HAS_EQUATION", "to_key": eq_key}]
        eq_draft.relations = list(eq_draft.relations or []) + [{"type": "HAS_FIGURE", "to_key": fig_key}]
        fig_draft.relations = _filter_known_relations(fig_draft.relations, context)
        eq_draft.relations = _filter_known_relations(eq_draft.relations, context)
    structure = context.structure or {}
    for draft in drafts:
        meta = draft.unit_meta or {}
        kind = str(meta.get("kind") or "")
        if kind not in {"concept", "section"}:
            continue
        section_anchor = str(meta.get("parent_anchor") or meta.get("anchor") or "")
        draft.concepts = merge_concepts(
            draft.concepts,
            fig_eq_concepts(draft.content, structure, section_anchor),
        )


def _load_figure_prompt() -> str:
    return load_prompt("figure-interpreter", DEFAULT_FIGURE_PROMPT)


def _section_default_role(section: dict[str, Any], allowed: set[SemanticRole]) -> SemanticRole:
    title = f"{section.get('id', '')} {section.get('title', '')}".lower()
    if str(section.get("id") or "").lower() == "abstract" and SemanticRole.SUMMARY in allowed:
        return SemanticRole.SUMMARY
    for hint, role in SECTION_ROLE_HINTS:
        if hint in title and role in allowed:
            return role
    if SemanticRole.PRINCIPLE in allowed:
        return SemanticRole.PRINCIPLE
    return next(iter(allowed), SemanticRole.DEFINITION)


def _section_for_page(structure: dict[str, Any] | None, page: int) -> str:
    chosen = ""
    for section in (structure or {}).get("sections") or []:
        if int(section.get("page") or 1) <= page:
            chosen = str(section.get("id") or section.get("title") or "")
    return chosen[:64]


def _page_of_section(structure: dict[str, Any] | None, section_id: str) -> int:
    for section in (structure or {}).get("sections") or []:
        if str(section.get("id") or "").lower() == section_id.lower():
            return int(section.get("page") or 1)
    pages = (structure or {}).get("pages") or []
    return int(pages[-1]["page"]) if pages else 1


def _parent_anchor_for_inventory(structure: dict[str, Any] | None, kind: str, item_id: str, page: int) -> str:
    sections = (structure or {}).get("sections") or []
    if kind == "fig":
        pattern = re.compile(rf"Fig(?:ure)?\.?\s*{re.escape(str(item_id))}\b", re.I)
    elif kind == "eq":
        pattern = re.compile(rf"\({re.escape(str(item_id))}\)")
    else:
        pattern = re.compile(rf"TABLE\s+{re.escape(str(item_id))}\b", re.I)
    for section in sections:
        sid = str(section.get("id") or "")
        if sid.lower().startswith("reference"):
            continue
        if pattern.search(section.get("text") or ""):
            return f"sec:{sid}"
    return _parent_anchor_for_page(structure, page)


def _parent_anchor_for_page(structure: dict[str, Any] | None, page: int) -> str:
    section_id = _section_for_page(structure, page)
    return f"sec:{section_id}" if section_id else ""


def _cite_relations(text: str) -> list[dict[str, Any]]:
    keys = re.findall(r"\[(\d{1,3})\]", text)
    return [{"type": "REFERENCES", "to_key": f"cite:[{num}]"} for num in keys]


def _eq_relations(text: str) -> list[dict[str, Any]]:
    refs = []
    for num in re.findall(r"\((\d{1,2})\)", text):
        if 1 <= int(num) <= 40:
            refs.append({"type": "EXPLAINED_BY", "to_key": f"eq:{num}"})
            refs.append({"type": "HAS_EQUATION", "to_key": f"eq:{num}"})
    return refs


def _fig_relations(text: str) -> list[dict[str, Any]]:
    return [{"type": "HAS_FIGURE", "to_key": f"fig:{num}"} for num in FIG_REF_RE.findall(text)]


def _body_relations(text: str) -> list[dict[str, Any]]:
    return _cite_relations(text) + _eq_relations(text) + _fig_relations(text)


def _filter_known_relations(relations: list[dict[str, Any]], context: DocumentContext) -> list[dict[str, Any]]:
    allowed = set()
    structure = context.structure or {}
    allowed.update(f"eq:{item.get('eq_id')}" for item in structure.get("equations") or [])
    allowed.update(f"fig:{item.get('fig_id')}" for item in structure.get("figures") or [])
    allowed.update(f"table:{item.get('table_id')}" for item in structure.get("tables") or [])
    allowed.update(f"cite:{item.get('key')}" for item in structure.get("citations") or [])
    allowed.update(f"sec:{item.get('id')}" for item in structure.get("sections") or [])
    filtered = []
    seen = set()
    for rel in relations:
        to_key = str(rel.get("to_key") or "")
        key = (str(rel.get("type") or ""), to_key)
        if not to_key or to_key not in allowed or key in seen:
            continue
        seen.add(key)
        filtered.append(rel)
    return filtered


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:180]
    return text[:180]


def _dedupe_drafts(drafts: list[KnowledgeUnitDraft]) -> list[KnowledgeUnitDraft]:
    seen: set[str] = set()
    unique: list[KnowledgeUnitDraft] = []
    for draft in drafts:
        anchor = str((draft.unit_meta or {}).get("anchor") or "")
        key = anchor or f"{draft.semantic_role.value}:{draft.title}:{draft.source_page}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(draft)
    return unique
