from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_stores, current_user
from app.domain.design_map import build_design_map
from app.domain.enums import RETRIEVAL_LIFECYCLES
from app.storage.db import get_session
from app.storage.models import Document, KnowledgeRelation, KnowledgeUnit, KnowledgeBase, KnowledgeAcl, User

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/design-map")
async def design_map(kb_id: str = "", session: AsyncSession = Depends(get_session), user: User = Depends(current_user)):
    bases = (await session.execute(select(KnowledgeBase))).scalars().all()
    rules = (await session.execute(select(KnowledgeAcl))).scalars().all()
    allowed = []
    for kb in bases:
        permitted = user.role == "admin" or kb.access_scope == "public"
        permitted |= kb.access_scope == "department" and bool(user.department) and kb.department == user.department
        permitted |= kb.access_scope == "project" and bool(user.project) and kb.project == user.project
        permitted |= any(r.kb_id == kb.id and r.permission in {"read", "write", "admin"} and (
            (r.principal_type == "user" and r.principal_id == user.id) or
            (r.principal_type == "role" and r.principal_id == user.role)
        ) for r in rules)
        if permitted:
            allowed.append(kb)
    allowed_ids = [kb.id for kb in allowed]
    if kb_id and kb_id not in allowed_ids:
        raise HTTPException(403, "无权访问该知识库")
    selected = [kb_id] if kb_id else allowed_ids
    units = (await session.execute(select(KnowledgeUnit).where(
        KnowledgeUnit.kb_id.in_(selected), KnowledgeUnit.lifecycle.in_(list(RETRIEVAL_LIFECYCLES))
    ).order_by(KnowledgeUnit.id))).scalars().all()
    docs = (await session.execute(select(Document).where(Document.kb_id.in_(selected)))).scalars().all()
    body = build_design_map(units, docs)
    body["knowledge_bases"] = [{"id": kb.id, "name": kb.name} for kb in allowed]
    return body

ROLE_EDGE = {
    "root_cause": "HAS_PROBLEM",
    "symptom": "HAS_PROBLEM",
    "prevention": "HAS_SOLUTION",
    "solution": "HAS_SOLUTION",
    "example": "HAS_SOLUTION",
    "constraint": "HAS_CONSTRAINT",
    "rule": "HAS_CONSTRAINT",
    "exception": "HAS_EXCEPTION",
    "definition": "DEFINES",
    "principle": "HAS_PROBLEM",
}

REL_LABEL = {
    "CAUSES": "HAS_PROBLEM",
    "SOLVES": "HAS_SOLUTION",
    "CONSTRAINS": "HAS_CONSTRAINT",
    "HAS_EXAMPLE": "HAS_EXAMPLE",
    "HAS_EXCEPTION": "HAS_EXCEPTION",
    "RELATED_TO": "RELATED_TO",
    "DEPENDS_ON": "DEPENDS_ON",
    "REFERENCES": "RELATED_TO",
}


def _concept_id(name: str) -> str:
    return f"concept:{name.strip()}"


def _short_label(text: str, limit: int = 12) -> str:
    value = (text or "").strip()
    return value if len(value) <= limit else value[:limit] + "…"


def _edge_type(role: str, relation_type: str = "") -> str:
    if relation_type:
        return REL_LABEL.get(relation_type, relation_type)
    return ROLE_EDGE.get(role, "RELATED_TO")


@router.get("")
async def graph(name: str = "", node_type: str = "", relation_type: str = "", session: AsyncSession = Depends(get_session)):
    stores = get_stores()
    keyword = (name or "").strip()
    if stores.neo4j.available and keyword:
        data = stores.neo4j.neighborhood(keyword)
        if data.get("nodes"):
            return {**data, "filters": _filters(data.get("nodes") or [], data.get("edges") or [])}

    stmt = select(KnowledgeUnit)
    if keyword:
        stmt = stmt.where(
            or_(
                KnowledgeUnit.title.ilike(f"%{keyword}%"),
                KnowledgeUnit.content.ilike(f"%{keyword}%"),
            )
        )
    units = (await session.execute(stmt.limit(40))).scalars().all()
    if not units:
        units = (await session.execute(select(KnowledgeUnit).limit(40))).scalars().all()

    ids = [unit.id for unit in units]
    rels = (
        await session.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.from_id.in_(ids) | KnowledgeRelation.to_id.in_(ids)
            )
        )
    ).scalars().all()
    extra_ids = {rel.from_id for rel in rels} | {rel.to_id for rel in rels}
    extra = (
        await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(list(extra_ids))))
    ).scalars().all() if extra_ids else []
    all_units = {unit.id: unit for unit in list(units) + list(extra)}

    doc_ids = [unit.document_id for unit in all_units.values() if unit.document_id]
    docs = {}
    if doc_ids:
        docs = {
            doc.id: doc
            for doc in (await session.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
        }

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    unit_index: dict[str, list[str]] = defaultdict(list)
    doc_index: dict[str, set[str]] = defaultdict(set)

    hub_name = keyword or "知识图谱"
    hub_id = _concept_id(hub_name)
    nodes[hub_id] = {
        "id": hub_id,
        "label": hub_name or "知识图谱",
        "type": "concept",
        "role": "concept",
        "description": "",
        "hub": True,
    }

    for unit in all_units.values():
        concepts = [str(item) for item in (unit.concepts or []) if str(item).strip()]
        if keyword and keyword.lower() not in " ".join(concepts).lower() and keyword.lower() not in unit.title.lower():
            concepts = concepts or [_short_label(unit.title, 16)]
        if not concepts:
            concepts = [_short_label(unit.title, 16)]
        related = [item for item in concepts if item.lower() != hub_name.lower()]
        if not related:
            related = [_short_label(unit.title.replace(hub_name, "").strip() or unit.title, 16)]
        for concept in related[:3]:
            nid = _concept_id(concept)
            nodes.setdefault(
                nid,
                {
                    "id": nid,
                    "label": concept,
                    "type": "concept",
                    "role": unit.semantic_role,
                    "description": (unit.content or "")[:180],
                    "hub": False,
                },
            )
            unit_index[nid].append(unit.id)
            if unit.document_id:
                doc_index[nid].add(unit.document_id)
            edges.append(
                {
                    "source": hub_id,
                    "target": nid,
                    "type": _edge_type(unit.semantic_role),
                    "weight": round(float(unit.confidence or 0.8), 2),
                }
            )
        unit_index[hub_id].append(unit.id)
        if unit.document_id:
            doc_index[hub_id].add(unit.document_id)
        if not nodes[hub_id]["description"] and unit.content:
            nodes[hub_id]["description"] = (unit.content or "")[:180]
        include_units = node_type in {"unit", "all"}
        if include_units:
            uid = f"unit:{unit.id}"
            nodes.setdefault(
                uid,
                {
                    "id": uid,
                    "label": _short_label(unit.title, 18),
                    "type": "unit",
                    "role": unit.semantic_role,
                    "description": (unit.content or "")[:180],
                    "hub": False,
                    "unit_id": unit.id,
                    "document_id": unit.document_id,
                },
            )
            unit_index[uid].append(unit.id)
            if unit.document_id:
                doc_index[uid].add(unit.document_id)

    if node_type in {"unit", "all"}:
        for rel in rels:
            src = all_units.get(rel.from_id)
            dst = all_units.get(rel.to_id)
            if not src or not dst:
                continue
            edges.append(
                {
                    "source": f"unit:{src.id}",
                    "target": f"unit:{dst.id}",
                    "type": _edge_type(dst.semantic_role, rel.relation_type),
                    "weight": 1,
                }
            )

    unique_edges = []
    seen = set()
    for edge in edges:
        key = (edge["source"], edge["target"], edge["type"])
        if key in seen or edge["source"] == edge["target"]:
            continue
        if edge["source"] not in nodes or edge["target"] not in nodes:
            continue
        seen.add(key)
        unique_edges.append(edge)

    if node_type and node_type not in {"", "all"}:
        nodes = {k: v for k, v in nodes.items() if v["type"] == node_type or v.get("hub")}
        unique_edges = [e for e in unique_edges if e["source"] in nodes and e["target"] in nodes]
    if relation_type and relation_type not in {"", "all"}:
        unique_edges = [e for e in unique_edges if e["type"] == relation_type]
        keep = {e["source"] for e in unique_edges} | {e["target"] for e in unique_edges}
        if hub_id in nodes:
            keep.add(hub_id)
        nodes = {k: v for k, v in nodes.items() if k in keep}

    result_nodes = []
    for node in nodes.values():
        related_docs = [
            {"id": docs[doc_id].id, "filename": docs[doc_id].filename}
            for doc_id in doc_index.get(node["id"], set())
            if doc_id in docs
        ]
        node["unit_count"] = len(set(unit_index.get(node["id"], [])))
        node["documents"] = related_docs
        node["unit_ids"] = list(dict.fromkeys(unit_index.get(node["id"], [])))
        result_nodes.append(node)

    return {
        "hub": hub_id,
        "nodes": result_nodes,
        "edges": unique_edges,
        "filters": _filters(result_nodes, unique_edges),
    }


def _filters(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "node_types": sorted({n.get("type") or "concept" for n in nodes}),
        "relation_types": sorted({e.get("type") or "RELATED_TO" for e in edges}),
    }
