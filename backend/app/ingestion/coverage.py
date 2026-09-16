from __future__ import annotations

from typing import Any

from app.domain.enums import KnowledgeType, SemanticRole, SourceLevel
from app.domain.strategy import KnowledgeUnitDraft

REQUIRED_ROLES = [
    SemanticRole.SUMMARY.value,
    SemanticRole.PRINCIPLE.value,
    SemanticRole.FORMULA.value,
    SemanticRole.PARAMETER.value,
    SemanticRole.METRIC.value,
    SemanticRole.REFERENCE.value,
]


def check_ingest_coverage(structure: dict[str, Any] | None, drafts: list[KnowledgeUnitDraft]) -> dict[str, Any]:
    structure = structure or {}
    genre = structure.get("genre") or ""
    anchors = {_anchor(draft) for draft in drafts}
    roles = {draft.semantic_role.value for draft in drafts}
    missing_equations = [
        str(item.get("eq_id"))
        for item in structure.get("equations") or []
        if f"eq:{item.get('eq_id')}" not in anchors
    ]
    missing_figures = [
        str(item.get("fig_id"))
        for item in structure.get("figures") or []
        if f"fig:{item.get('fig_id')}" not in anchors
    ]
    missing_tables = [
        str(item.get("table_id"))
        for item in structure.get("tables") or []
        if f"table:{item.get('table_id')}" not in anchors
    ]
    missing_citations = [
        str(item.get("key"))
        for item in structure.get("citations") or []
        if f"cite:{item.get('key')}" not in anchors
    ]
    required_roles = list(structure.get("required_roles", REQUIRED_ROLES if genre == "academic_paper" else []))
    if genre == "academic_paper" and not (structure.get("equations") or []):
        required_roles = [role for role in required_roles if role != SemanticRole.FORMULA.value]
    missing_roles = [role for role in required_roles if role not in roles]
    inventory_total = (
        len(structure.get("equations") or [])
        + len(structure.get("figures") or [])
        + len(structure.get("tables") or [])
        + len(structure.get("citations") or [])
        + len(required_roles)
    )
    missing_count = (
        len(missing_equations)
        + len(missing_figures)
        + len(missing_tables)
        + len(missing_citations)
        + len(missing_roles)
    )
    covered = max(inventory_total - missing_count, 0)
    score = round(covered / inventory_total, 2) if inventory_total else 1.0
    ready_miss = _retrieval_ready_gaps(structure, drafts)
    ready_total = max(
        len(structure.get("equations") or [])
        + len(structure.get("figures") or [])
        + len(structure.get("citations") or []),
        1,
    )
    retrieval_ready_score = round(max(ready_total - len(ready_miss), 0) / ready_total, 2)
    parse_quality = structure.get("parse_quality") or {}
    text_len = int(parse_quality.get("text_len") or len(str(structure.get("text") or "")))
    empty_text = genre == "academic_paper" and text_len < 80
    complete = score >= float(structure.get("coverage_threshold", 0.9)) and not missing_equations and not missing_citations and not empty_text
    return {
        "genre": genre,
        "score": score,
        "complete": complete,
        "missing_equations": missing_equations,
        "missing_figures": missing_figures,
        "missing_tables": missing_tables,
        "missing_citations": missing_citations,
        "missing_roles": missing_roles,
        "required_roles": required_roles,
        "unit_count": len(drafts),
        "retrieval_ready_score": retrieval_ready_score,
        "retrieval_ready_gaps": ready_miss,
        "pages_ocr": parse_quality.get("pages_ocr") or 0,
        "empty_text": empty_text,
    }


def apply_coverage_stubs(
    structure: dict[str, Any] | None,
    drafts: list[KnowledgeUnitDraft],
    knowledge_type: KnowledgeType = KnowledgeType.TECHNICAL_CONCEPT,
) -> tuple[list[KnowledgeUnitDraft], dict[str, Any]]:
    structure = structure or {}
    existing = {_anchor(draft) for draft in drafts}
    extras: list[KnowledgeUnitDraft] = []
    for eq in structure.get("equations") or []:
        anchor = f"eq:{eq.get('eq_id')}"
        if anchor not in existing:
            extras.append(
                _stub(
                    title=f"Equation ({eq.get('eq_id')}) missing extraction",
                    content=str(eq.get("raw") or eq.get("nearby_text") or anchor),
                    role=SemanticRole.FORMULA,
                    knowledge_type=knowledge_type,
                    page=int(eq.get("page") or 1),
                    anchor=anchor,
                    meta={"kind": "equation", "eq_id": eq.get("eq_id"), "stub": True},
                )
            )
            existing.add(anchor)
    for fig in structure.get("figures") or []:
        anchor = f"fig:{fig.get('fig_id')}"
        if anchor not in existing:
            extras.append(
                _stub(
                    title=f"Fig. {fig.get('fig_id')}",
                    content=str(fig.get("caption") or anchor),
                    role=SemanticRole.INTERFACE,
                    knowledge_type=knowledge_type,
                    page=int(fig.get("page") or 1),
                    anchor=anchor,
                    meta={"kind": "figure", "fig_id": fig.get("fig_id"), "stub": True},
                )
            )
            existing.add(anchor)
    for table in structure.get("tables") or []:
        anchor = f"table:{table.get('table_id')}"
        if anchor not in existing:
            extras.append(
                _stub(
                    title=f"TABLE {table.get('table_id')}",
                    content=str(table.get("caption") or anchor),
                    role=SemanticRole.METRIC,
                    knowledge_type=knowledge_type,
                    page=int(table.get("page") or 1),
                    anchor=anchor,
                    meta={"kind": "table", "table_id": table.get("table_id"), "stub": True},
                )
            )
            existing.add(anchor)
    for cite in structure.get("citations") or []:
        anchor = f"cite:{cite.get('key')}"
        if anchor not in existing:
            extras.append(
                _stub(
                    title=f"Reference {cite.get('key')}",
                    content=str(cite.get("text") or cite.get("key")),
                    role=SemanticRole.REFERENCE,
                    knowledge_type=knowledge_type,
                    page=1,
                    anchor=anchor,
                    meta={"kind": "citation", "cite_key": cite.get("key"), "stub": True},
                )
            )
            existing.add(anchor)
    merged = list(drafts) + extras
    coverage = check_ingest_coverage(structure, merged)
    if coverage.get("missing_roles"):
        missing = ", ".join(coverage["missing_roles"])
        merged.append(
            _stub(
                title="Ingestion coverage gaps",
                content=f"Missing semantic roles after extraction: {missing}",
                role=SemanticRole.SUMMARY,
                knowledge_type=knowledge_type,
                page=1,
                anchor="coverage:gaps",
                meta={"kind": "coverage", "missing_roles": coverage["missing_roles"]},
            )
        )
        coverage = check_ingest_coverage(structure, merged)
        coverage["stub_count"] = len(extras) + 1
    else:
        coverage["stub_count"] = len(extras)
    return merged, coverage


def _stub(
    title: str,
    content: str,
    role: SemanticRole,
    knowledge_type: KnowledgeType,
    page: int,
    anchor: str,
    meta: dict[str, Any],
) -> KnowledgeUnitDraft:
    return KnowledgeUnitDraft(
        title=title[:180],
        content=content,
        semantic_role=role,
        knowledge_type=knowledge_type,
        importance="core",
        source_span=content[:500],
        source_page=page,
        parent_context="coverage",
        confidence=0.4,
        unit_meta={"anchor": anchor, **meta},
        source_level=SourceLevel.AI_GENERATED.value,
    )


def _retrieval_ready_gaps(structure: dict[str, Any], drafts: list[KnowledgeUnitDraft]) -> list[str]:
    by_anchor = {_anchor(draft): draft for draft in drafts}
    gaps: list[str] = []
    for item in structure.get("figures") or []:
        draft = by_anchor.get(f"fig:{item.get('fig_id')}")
        meta = (draft.unit_meta if draft else {}) or {}
        content = (draft.content if draft else "") or ""
        if not (meta.get("image_key") or item.get("image_key") or "Description:" in content or len(str(item.get("caption") or "")) >= 12):
            gaps.append(f"fig:{item.get('fig_id')}")
        elif draft and not (meta.get("image_key") or "Description:" in content):
            gaps.append(f"fig:{item.get('fig_id')}:vision")
    for item in structure.get("equations") or []:
        draft = by_anchor.get(f"eq:{item.get('eq_id')}")
        meta = (draft.unit_meta if draft else {}) or {}
        if not (meta.get("latex") or item.get("latex") or meta.get("image_key") or item.get("image_key")):
            gaps.append(f"eq:{item.get('eq_id')}")
    for item in structure.get("citations") or []:
        draft = by_anchor.get(f"cite:{item.get('key')}")
        text = (draft.content if draft else "") or str(item.get("text") or "")
        if not text.strip():
            gaps.append(f"cite:{item.get('key')}")
    return gaps


def _anchor(draft: KnowledgeUnitDraft) -> str:
    return str((draft.unit_meta or {}).get("anchor") or "")
