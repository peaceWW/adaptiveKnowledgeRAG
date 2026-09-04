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
        must: list[FieldCondition] = [
            FieldCondition(key="lifecycle", match=MatchValue(value=lifecycle)),
        ]
        if kb_id:
            must.append(FieldCondition(key="kb_id", match=MatchValue(value=kb_id)))
        if roles:
            must.append(FieldCondition(key="semantic_role", match=MatchAny(any=roles)))
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
        return [
            {
                "id": str(hit.id),
                "score": float(hit.score or 0),
                "payload": hit.payload or {},
            }
            for hit in results
        ]

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
            if payload.get("lifecycle") not in {lifecycle, "APPROVED"}:
                continue
            if kb_id and payload.get("kb_id") != kb_id:
                continue
            if allowed_kbs and payload.get("kb_id") not in allowed_kbs:
                continue
            if roles and payload.get("semantic_role") not in roles:
                continue
            score = _cosine(vector, vec)
            scored.append({"id": unit_id, "score": score, "payload": payload})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = sum(x * x for x in a) ** 0.5 or 1.0
    db = sum(x * x for x in b) ** 0.5 or 1.0
    return num / (da * db)
