from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_stores
from app.storage.db import get_session
from app.storage.models import KnowledgeAcl, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User))
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "department": u.department,
            "project": u.project,
        }
        for u in result.scalars().all()
    ]


@router.get("/acl")
async def list_acl(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(KnowledgeAcl))
    return [
        {
            "id": a.id,
            "kb_id": a.kb_id,
            "principal_type": a.principal_type,
            "principal_id": a.principal_id,
            "permission": a.permission,
        }
        for a in result.scalars().all()
    ]


@router.get("/health")
async def health():
    stores = get_stores()
    settings = get_settings()
    return {
        "postgres": True,
        "qdrant": stores.qdrant.available,
        "minio": stores.minio.available,
        "elasticsearch": stores.es.available,
        "neo4j": stores.neo4j.available,
        "model_gateway": settings.use_real_model,
        "llm": settings.model_llm,
        "vision": settings.vision_model,
        "embedding": settings.model_embedding,
        "embedding_dim": settings.embedding_dim,
        "rerank": settings.model_rerank,
    }
