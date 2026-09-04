from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model_gateway.gateway import ModelGateway
from app.storage.db import get_session
from app.storage.es_store import ElasticStore
from app.storage.minio_store import MinioStore
from app.storage.models import User
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore


@dataclass
class AppStores:
    gateway: ModelGateway
    qdrant: QdrantStore
    minio: MinioStore
    es: ElasticStore
    neo4j: Neo4jStore


stores: AppStores | None = None


def get_stores() -> AppStores:
    if stores is None:
        raise RuntimeError("stores not initialized")
    return stores


async def current_user(
    session: AsyncSession = Depends(get_session),
    x_user: str | None = Header(default="admin", alias="X-User"),
) -> User:
    result = await session.execute(select(User).where(User.username == (x_user or "admin")))
    user = result.scalar_one_or_none()
    if not user:
        result = await session.execute(select(User).where(User.role == "admin"))
        user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user
