# 把用户问题收成可检索词。中英混排（如「RX什么时候使用ADC」）按空白切会整句匹配失败。
from __future__ import annotations

import re

LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{1,}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def query_terms(query: str) -> list[str]:
    """抽出英文缩写与中文片段，供关键字 / 文档索引命中英文论文正文。"""
    text = (query or "").strip()
    if not text:
        return []
    terms: list[str] = []
    terms.extend(LATIN_RE.findall(text))
    terms.extend(CJK_RE.findall(text))
    terms.extend(part for part in re.split(r"\s+", text) if len(part) >= 2)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = term.lower()
        if key in seen or len(term) < 2:
            continue
        seen.add(key)
        result.append(term)
    return result


def retrieval_query(query: str) -> str:
    """给 ES multi_match 用：优先把 ADC/RX 等独立出来，避免整句中文无法分词命中英文。"""
    terms = query_terms(query)
    return " ".join(terms) if terms else (query or "")
