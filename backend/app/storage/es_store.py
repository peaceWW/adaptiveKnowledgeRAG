from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from elasticsearch import AsyncElasticsearch

from app.config import get_settings

logger = logging.getLogger(__name__)


class ElasticStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.index = settings.elasticsearch_index
        self.available = False
        self.client: AsyncElasticsearch | None = None
        self._local: dict[str, dict[str, Any]] = {}
        from urllib.parse import urlparse

        parsed = urlparse(settings.elasticsearch_url)
        try:
            with socket.create_connection((parsed.hostname or "localhost", parsed.port or 9200), timeout=0.4):
                pass
        except OSError:
            logger.warning("Elasticsearch unreachable")
            return
        try:
            self.client = AsyncElasticsearch(settings.elasticsearch_url, request_timeout=3)
        except Exception as exc:
            logger.warning("Elasticsearch client init failed: %s", exc)
            self.client = None

    async def ensure_index(self) -> None:
        if not self.client:
            return
        try:
            exists = await asyncio.wait_for(self.client.indices.exists(index=self.index), timeout=3)
            if not exists:
                await asyncio.wait_for(
                    self.client.indices.create(
                        index=self.index,
                        mappings={
                            "properties": {
                                "title": {"type": "text"},
                                "content": {"type": "text"},
                                "concepts": {"type": "keyword"},
                                "semantic_role": {"type": "keyword"},
                                "kb_id": {"type": "keyword"},
                                "lifecycle": {"type": "keyword"},
                                "knowledge_type": {"type": "keyword"},
                                "domain": {"type": "keyword"},
                                "keywords": {"type": "keyword"},
                                "doc_id": {"type": "keyword"},
                                "filename": {"type": "keyword"},
                            }
                        },
                    ),
                    timeout=3,
                )
            self.available = True
        except Exception as exc:
            logger.warning("Elasticsearch unavailable: %s", exc)
            self.available = False

    async def upsert(self, unit_id: str, body: dict[str, Any]) -> None:
        self._local[unit_id] = body
        if not self.client or not self.available:
            return
        try:
            await self.client.index(index=self.index, id=unit_id, document=body)
        except Exception as exc:
            logger.warning("ES upsert failed: %s", exc)

    async def delete(self, doc_id: str) -> None:
        self._local.pop(doc_id, None)
        self._local.pop(f"doc:{doc_id}", None)
        if not self.client or not self.available:
            return
        try:
            await self.client.delete(index=self.index, id=doc_id, ignore=[404])
            await self.client.delete(index=self.index, id=f"doc:{doc_id}", ignore=[404])
        except Exception as exc:
            logger.warning("ES delete failed: %s", exc)

    async def upsert_document_index(self, doc_id: str, body: dict[str, Any]) -> None:
        await self.upsert(f"doc:{doc_id}", {**body, "doc_id": doc_id, "index_kind": "document"})

    async def delete_document_index(self, doc_id: str) -> None:
        await self.delete(f"doc:{doc_id}")

    def _query_tokens(self, query: str) -> list[str]:
        return [tok.lower() for tok in query.split() if len(tok) >= 2] or [query.lower()]

    def _local_blob(self, body: dict[str, Any]) -> str:
        parts = [
            str(body.get("title") or ""),
            str(body.get("content") or ""),
            str(body.get("filename") or ""),
            " ".join(body.get("concepts") or []),
            " ".join(body.get("keywords") or []),
            str(body.get("metadata") or ""),
        ]
        return " ".join(parts).lower()

    async def search_document_ids(self, query: str, kb_id: str | None = None) -> list[str]:
        tokens = self._query_tokens(query)
        matched: list[str] = []
        for key, body in self._local.items():
            if body.get("index_kind") != "document":
                continue
            if kb_id and body.get("kb_id") != kb_id:
                continue
            blob = self._local_blob(body)
            if any(tok in blob for tok in tokens):
                matched.append(str(body.get("doc_id") or key.removeprefix("doc:")))
        if not self.client or not self.available:
            return list(dict.fromkeys(matched))
        filters: list[dict[str, Any]] = [{"term": {"index_kind": "document"}}]
        if kb_id:
            filters.append({"term": {"kb_id": kb_id}})
        try:
            result = await self.client.search(
                index=self.index,
                size=50,
                query={
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["keywords^3", "filename^2", "title", "content"],
                                }
                            }
                        ],
                        "filter": filters,
                    }
                },
            )
            for hit in result.get("hits", {}).get("hits", []):
                source = hit.get("_source") or {}
                doc_id = source.get("doc_id") or str(hit.get("_id") or "").removeprefix("doc:")
                if doc_id:
                    matched.append(str(doc_id))
        except Exception as exc:
            logger.warning("ES document index search failed: %s", exc)
        return list(dict.fromkeys(matched))

    async def search(
        self,
        query: str,
        limit: int = 50,
        kb_id: str | None = None,
        roles: list[str] | None = None,
        lifecycle: str = "PUBLISHED",
    ) -> list[dict[str, Any]]:
        tokens = self._query_tokens(query)
        local_hits = []
        for unit_id, body in self._local.items():
            if body.get("index_kind") == "document":
                continue
            if lifecycle and body.get("lifecycle") not in {lifecycle, "APPROVED", "PUBLISHED"}:
                continue
            if kb_id and body.get("kb_id") != kb_id:
                continue
            if roles and body.get("semantic_role") not in roles:
                continue
            if any(tok in self._local_blob(body) for tok in tokens):
                local_hits.append({"id": unit_id, "score": 1.0, "source": body})
        if not self.client or not self.available:
            return local_hits[:limit]
        filters: list[dict[str, Any]] = [{"term": {"lifecycle": lifecycle}}]
        if kb_id:
            filters.append({"term": {"kb_id": kb_id}})
        if roles:
            filters.append({"terms": {"semantic_role": roles}})
        try:
            result = await self.client.search(
                index=self.index,
                size=limit,
                query={
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title^3", "content", "concepts^2", "keywords^3", "filename"],
                                }
                            }
                        ],
                        "filter": filters,
                    }
                },
            )
            hits = result.get("hits", {}).get("hits", [])
            return [
                {
                    "id": hit["_id"],
                    "score": float(hit.get("_score") or 0),
                    "source": hit.get("_source", {}),
                }
                for hit in hits
            ]
        except Exception as exc:
            logger.warning("ES search failed: %s", exc)
            return local_hits[:limit]

    async def close(self) -> None:
        if self.client:
            await self.client.close()
