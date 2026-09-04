from __future__ import annotations

from typing import Any

import pymupdf as fitz


def parse_bytes(filename: str, data: bytes) -> dict[str, Any]:
    if filename.lower().endswith((".md", ".txt", ".html")):
        text = data.decode("utf-8", errors="ignore")
        return {
            "text": text,
            "pages": [{"page": 1, "text": text}],
            "chapters": _headings_from_text(text),
        }
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        text = data.decode("utf-8", errors="ignore")
        return {"text": text, "pages": [{"page": 1, "text": text}], "chapters": _headings_from_text(text)}

    pages = []
    chapters = []
    full_parts = []
    for idx, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages.append({"page": idx, "text": text})
        full_parts.append(text)
        for heading in _headings_from_text(text, page=idx):
            chapters.append(heading)
    return {
        "text": "\n".join(full_parts),
        "pages": pages,
        "chapters": chapters or _headings_from_text("\n".join(full_parts)),
    }


def _headings_from_text(text: str, page: int = 1) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            chapters.append({"title": stripped.lstrip("# ").strip(), "level": min(level, 4), "page": page})
        elif _looks_like_heading(stripped):
            chapters.append({"title": stripped, "level": 2, "page": page})
    return chapters


def _looks_like_heading(line: str) -> bool:
    if len(line) > 80:
        return False
    if line[:1].isdigit() and ("." in line[:6] or " " in line[:4]):
        return True
    keywords = ("Chapter", "Section", "定义", "原理", "约束", "示例", "CDC", "Setup", "Hold")
    return any(key in line for key in keywords) and len(line.split()) <= 12
