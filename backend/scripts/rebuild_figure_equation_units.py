"""回写已抽取文档的图/公式/章节文本，补互指关系并重建向量与知识图谱投影。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select

from app.domain.enums import RelationType
from app.domain.payload import unit_embed_text, unit_vector_payload
from app.ingestion.catalog_sync import sync_catalog_from_document
from app.ingestion.refresh_units import apply_bundle_to_units, unit_figure_equation_pairs
from app.model_gateway.gateway import ModelGateway
from app.storage import db as storage_db
from app.storage.es_store import ElasticStore
from app.storage.models import Document, KnowledgeRelation, KnowledgeUnit
from app.storage.qdrant_store import QdrantStore


async def _ensure_relation(session, from_id: str, to_id: str, rel_type: str) -> bool:
    existing = await session.execute(
        select(KnowledgeRelation).where(
            KnowledgeRelation.from_id == from_id,
            KnowledgeRelation.to_id == to_id,
            KnowledgeRelation.relation_type == rel_type,
        )
    )
    if existing.scalar_one_or_none():
        return False
    session.add(KnowledgeRelation(from_id=from_id, to_id=to_id, relation_type=rel_type, to_kind="unit"))
    return True


async def rebuild() -> dict[str, int]:
    """遍历全部文档：整理图/公式正文与概念，写入 HAS_FIGURE/HAS_EQUATION，再重嵌入。"""
    await storage_db.init_db()
    gateway = ModelGateway()
    qdrant = QdrantStore()
    es = ElasticStore()
    stats = {"documents": 0, "units": 0, "relations": 0, "embedded": 0}
    async with storage_db.SessionLocal() as session:
        docs = (await session.execute(select(Document))).scalars().all()
        for doc in docs:
            units = (
                await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.document_id == doc.id))
            ).scalars().all()
            if not units:
                continue
            structure = doc.structure or {}
            paper_title = str((doc.index_meta or {}).get("title") or (structure.get("metadata") or {}).get("title") or doc.filename)
            apply_bundle_to_units(list(units), structure, paper_title)
            by_anchor = {str((unit.unit_meta or {}).get("anchor") or ""): unit for unit in units}
            for fig_id, eq_id in unit_figure_equation_pairs(list(units)):
                fig = by_anchor.get(f"fig:{fig_id}")
                eq = by_anchor.get(f"eq:{eq_id}")
                if not fig or not eq:
                    continue
                if await _ensure_relation(session, fig.id, eq.id, RelationType.HAS_EQUATION.value):
                    stats["relations"] += 1
                if await _ensure_relation(session, eq.id, fig.id, RelationType.HAS_FIGURE.value):
                    stats["relations"] += 1
            texts = [unit_embed_text(unit) for unit in units]
            vectors = gateway.embed(texts) if texts else []
            for unit, vector in zip(units, vectors, strict=False):
                qdrant.upsert(unit.id, vector, unit_vector_payload(unit))
                if es:
                    payload = unit_vector_payload(unit)
                    await es.upsert(
                        unit.id,
                        {
                            "title": unit.title,
                            "content": unit.content,
                            "concepts": unit.concepts,
                            "semantic_role": unit.semantic_role,
                            "kb_id": unit.kb_id,
                            "lifecycle": unit.lifecycle,
                            "knowledge_type": unit.knowledge_type,
                            "domain": unit.domain,
                            "kind": payload.get("kind") or "",
                            "document_id": unit.document_id,
                        },
                    )
                stats["embedded"] += 1
            await sync_catalog_from_document(session, doc, list(units))
            stats["documents"] += 1
            stats["units"] += len(units)
        await session.commit()
    await es.close()
    return stats


if __name__ == "__main__":
    result = asyncio.run(rebuild())
    print(
        f"rebuilt documents={result['documents']} units={result['units']} "
        f"relations={result['relations']} embedded={result['embedded']}"
    )
