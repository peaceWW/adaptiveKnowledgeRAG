from __future__ import annotations

import logging
import socket
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import get_settings
from app.domain.enums import RETRIEVAL_LIFECYCLES

logger = logging.getLogger(__name__)


def _reachable(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class QdrantStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: QdrantClient | None = None
        self.available = False
        self._memory: dict[str, tuple[list[float], dict[str, Any]]] = {}
        try:
            from urllib.parse import urlparse

            parsed = urlparse(self.settings.qdrant_url)
            if not _reachable(parsed.hostname or "localhost", parsed.port or 6333):
                raise ConnectionError("qdrant not reachable")
            self.client = QdrantClient(url=self.settings.qdrant_url, timeout=2, check_compatibility=False)
            self.client.get_collections()
            self.available = True
            self.ensure_collection()
        except Exception as exc:
            logger.warning("Qdrant unavailable, using in-memory vectors: %s", exc)
            self.client = None
            self.available = False

    def ensure_collection(self) -> None:
        """创建 collection；已存在时只告警向量维与 EMBEDDING_DIM 不一致，不自动删库。"""
        if not self.client:
            return
        name = self.settings.qdrant_collection
        collections = [c.name for c in self.client.get_collections().collections]
        if name not in collections:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self.settings.embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
            return
        size = self._collection_vector_size(name)
        if size and size != self.settings.embedding_dim:
            logger.warning(
                "Qdrant collection %s vector size is %s, EMBEDDING_DIM=%s; recreate the collection after changing embedding models",
                name,
                size,
                self.settings.embedding_dim,
            )

    def _collection_vector_size(self, name: str) -> int | None:
        """读已有 collection 的向量维，换千问 embedding 后若不一致需要重建。"""
        try:
            info = self.client.get_collection(name)
            params = info.config.params.vectors
            if hasattr(params, "size") and params.size:
                return int(params.size)
            if isinstance(params, dict) and params:
                first = next(iter(params.values()))
                if hasattr(first, "size") and first.size:
                    return int(first.size)
                if isinstance(first, dict) and first.get("size"):
                    return int(first["size"])
        except Exception as exc:
            logger.warning("Could not read Qdrant collection vector size: %s", exc)
        return None

    def upsert(self, unit_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._memory[unit_id] = (vector, payload)
        if not self.client:
            return
        self.client.upsert(
            collection_name=self.settings.qdrant_collection,
            points=[PointStruct(id=unit_id, vector=vector, payload=payload)],
        )

    def delete(self, unit_id: str) -> None:
        self._memory.pop(unit_id, None)
        if not self.client:
            return
        self.client.delete(
            collection_name=self.settings.qdrant_collection,
            points_selector=[unit_id],
        )

    def search(
        self,
        vector: list[float],
        limit: int = 50,
        kb_id: str | None = None,
        roles: list[str] | None = None,
        lifecycle: str = "PUBLISHED",
        extra_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.client:
            try:
                return self._qdrant_search(vector, limit, kb_id, roles, lifecycle, extra_filters)
            except Exception as exc:
                logger.warning("Qdrant search failed, memory fallback: %s", exc)
        return self._memory_search(vector, limit, kb_id, roles, lifecycle, extra_filters)

    def _qdrant_search(
        self,
        vector: list[float],
        limit: int,
        kb_id: str | None,
        roles: list[str] | None,
        lifecycle: str,
        extra_filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        assert self.client is not None
        lifecycles = list(RETRIEVAL_LIFECYCLES) if lifecycle in RETRIEVAL_LIFECYCLES else [lifecycle]
        must: list[FieldCondition] = [
            FieldCondition(key="lifecycle", match=MatchAny(any=list(dict.fromkeys(lifecycles)))),
        ]
        if kb_id:
            must.append(FieldCondition(key="kb_id", match=MatchValue(value=kb_id)))
        if extra_filters:
            for key, value in extra_filters.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    must.append(FieldCondition(key=key, match=MatchAny(any=value)))
                else:
                    must.append(FieldCondition(key=key, match=MatchValue(value=value)))
        results = self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=vector,
            query_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
        )
        hits = [
            {
                "id": str(hit.id),
                "score": float(hit.score or 0),
                "payload": hit.payload or {},
            }
            for hit in results
        ]
        return _boost_roles(hits, roles)

    def _memory_search(
        self,
        vector: list[float],
        limit: int,
        kb_id: str | None,
        roles: list[str] | None,
        lifecycle: str,
        extra_filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        allowed_kbs = None
        if extra_filters and extra_filters.get("kb_id"):
            allowed_kbs = extra_filters["kb_id"]
            if not isinstance(allowed_kbs, list):
                allowed_kbs = [allowed_kbs]
        for unit_id, (vec, payload) in self._memory.items():
            if payload.get("lifecycle") not in (
                RETRIEVAL_LIFECYCLES if lifecycle in RETRIEVAL_LIFECYCLES else {lifecycle}
            ):
                continue
            if kb_id and payload.get("kb_id") != kb_id:
                continue
            if allowed_kbs and payload.get("kb_id") not in allowed_kbs:
                continue
            extra_kind = extra_filters.get("kind") if extra_filters else None
            if extra_kind:
                accepted = extra_kind if isinstance(extra_kind, list) else [extra_kind]
                if payload.get("kind") not in accepted:
                    continue
            score = _cosine(vector, vec)
            scored.append({"id": unit_id, "score": score, "payload": payload})
        scored = _boost_roles(scored, roles)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]


def _boost_roles(hits: list[dict[str, Any]], roles: list[str] | None, weight: float = 1.2) -> list[dict[str, Any]]:
    if not roles:
        return hits
    wanted = set(roles)
    for hit in hits:
        role = (hit.get("payload") or {}).get("semantic_role")
        if role in wanted:
            hit["score"] = float(hit.get("score") or 0) * weight
    hits.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return hits


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = sum(x * x for x in a) ** 0.5 or 1.0
    db = sum(x * x for x in b) ** 0.5 or 1.0
    return num / (da * db)
