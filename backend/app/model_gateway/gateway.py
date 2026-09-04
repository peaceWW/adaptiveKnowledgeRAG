from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from typing import Any

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class ModelGateway:
    """Unified LLM / embedding / rerank entry. Falls back to heuristics when no API key."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: OpenAI | None = None
        if self.settings.use_real_model:
            self.client = OpenAI(
                api_key=self.settings.model_api_key,
                base_url=self.settings.model_base_url,
            )

    def chat_json(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        if self.client:
            try:
                resp = self.client.chat.completions.create(
                    model=self.settings.model_llm,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = resp.choices[0].message.content or "{}"
                return json.loads(content)
            except Exception as exc:
                logger.warning("LLM call failed, using heuristic: %s", exc)
        return {}

    def chat_text(self, system: str, user: str, temperature: float = 0.2) -> str:
        if self.client:
            try:
                resp = self.client.chat.completions.create(
                    model=self.settings.model_llm,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                logger.warning("LLM text call failed: %s", exc)
        return ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.client:
            try:
                resp = self.client.embeddings.create(
                    model=self.settings.model_embedding,
                    input=texts,
                )
                return [item.embedding for item in resp.data]
            except Exception as exc:
                logger.warning("Embedding failed, using hash vectors: %s", exc)
        return [self._hash_vector(text) for text in texts]

    def rerank(self, query: str, documents: list[str], top_n: int = 20) -> list[tuple[int, float]]:
        if not documents:
            return []
        if self.client:
            scored = self.chat_json(
                "You are a reranker. Return JSON {\"scores\": [{\"index\":0,\"score\":0.0}]}.",
                json.dumps({"query": query, "documents": documents[:40]}, ensure_ascii=False),
            )
            scores = scored.get("scores") or []
            if scores:
                ordered = sorted(scores, key=lambda x: x.get("score", 0), reverse=True)
                return [(int(item["index"]), float(item["score"])) for item in ordered[:top_n]]
        q_tokens = set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query.lower()))
        ranked: list[tuple[int, float]] = []
        for idx, doc in enumerate(documents):
            d_tokens = set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", doc.lower()))
            overlap = len(q_tokens & d_tokens)
            score = overlap / max(len(q_tokens) or 1, 1)
            ranked.append((idx, score))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_n]

    def _hash_vector(self, text: str) -> list[float]:
        dim = self.settings.embedding_dim
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        seed = digest
        while len(values) < dim:
            for byte in seed:
                values.append((byte / 127.5) - 1.0)
                if len(values) >= dim:
                    break
            seed = hashlib.sha256(seed + text.encode("utf-8")).digest()
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
