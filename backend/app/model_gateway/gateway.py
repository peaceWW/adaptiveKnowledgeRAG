from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
from typing import Any

from openai import OpenAI, AsyncOpenAI

from app.config import get_settings
from app.observability.pipeline_log import step as pipeline_step

logger = logging.getLogger(__name__)


def parse_json_content(content: str) -> dict[str, Any]:
    """从模型回复抽出 JSON 对象。部分千问模型对 json_object 不稳，会夹 markdown 或前后废话。"""
    text = (content or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


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
        pipeline_step(
            "model",
            "init",
            inputs={
                "base_url": self.settings.model_base_url,
                "llm": self.settings.model_llm,
                "vision": self.settings.vision_model,
                "embedding": self.settings.model_embedding,
                "embedding_dim": self.settings.embedding_dim,
            },
            result={"use_real": self.settings.use_real_model, "has_client": bool(self.client)},
        )

    def chat_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        temperature: float = 0.0,
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        if not self.client or not image_bytes:
            return {}
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            },
        ]
        return self._complete_json(self.settings.vision_model, messages, temperature)

    def chat_json(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        if not self.client:
            return {}
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self._complete_json(self.settings.model_llm, messages, temperature)

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

    async def chat_text_stream(self, system: str, user: str):
        if not self.client:
            return
        async with AsyncOpenAI(api_key=self.settings.model_api_key, base_url=self.settings.model_base_url) as client:
            stream = await client.chat.completions.create(
                model=self.settings.model_llm, temperature=0.2, stream=True,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            async with stream:
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        """按提供商批次上限切分。千问 text-embedding-v3 单次 >10 会 400，整篇抽取会退回 hash 向量。"""
        if not texts:
            return []
        if self.client:
            try:
                vectors: list[list[float]] = []
                batch = max(1, int(self.settings.embedding_batch_size or 10))
                for start in range(0, len(texts), batch):
                    chunk = texts[start : start + batch]
                    resp = self.client.embeddings.create(
                        model=self.settings.model_embedding,
                        input=chunk,
                    )
                    ordered = sorted(resp.data, key=lambda item: getattr(item, "index", 0))
                    vectors.extend(item.embedding for item in ordered)
                if len(vectors) == len(texts):
                    return vectors
                logger.warning("Embedding count mismatch %s != %s, using hash vectors", len(vectors), len(texts))
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

    def _complete_json(self, model: str, messages: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        """先走 json_object；失败或解析不出对象时去掉 response_format 再抽 JSON。"""
        last_error: Exception | None = None
        for use_format in (True, False):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "temperature": temperature,
                    "messages": messages,
                }
                if use_format:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = self.client.chat.completions.create(**kwargs)
                parsed = parse_json_content(resp.choices[0].message.content or "")
                if parsed:
                    return parsed
            except Exception as exc:
                last_error = exc
                logger.warning("LLM json call failed (model=%s format=%s): %s", model, use_format, exc)
        if last_error:
            logger.warning("LLM call failed, using heuristic: %s", last_error)
        return {}

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
