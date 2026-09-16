from __future__ import annotations

import re
from typing import Any

import pymupdf as fitz

from app.ingestion.academic_parse import headings_from_text, looks_like_academic_paper, parse_pdf_document
from app.observability.pipeline_log import step as pipeline_step, structure_digest
from app.ingestion.text_inventory import enrich_text_inventory


def parse_bytes(filename: str, data: bytes) -> dict[str, Any]:
    lower = filename.lower()
    if lower.endswith((".md", ".txt", ".html")):
        text = data.decode("utf-8", errors="ignore")
        pages = [{"page": 1, "text": text, "reading_order": "single"}]
        metadata = {"title": filename}
        genre = "academic_paper" if looks_like_academic_paper(text, filename=filename) else "generic"
        from app.ingestion.academic_parse import (
            collect_citations,
            extract_equations,
            extract_figure_captions,
            split_ieee_sections,
            TABLE_RE,
        )

        sections = split_ieee_sections(pages) if genre == "academic_paper" else []
        equations = extract_equations([], 1, text)
        citations = collect_citations(pages, [])
        figures = extract_figure_captions(text, 1)
        tables = []
        if genre == "academic_paper":
            for line in text.splitlines():
                match = TABLE_RE.match(line.strip())
                if match:
                    tables.append(
                        {"table_id": str(match.group(1)), "caption": match.group(2).strip(), "page": 1, "rows": []}
                    )
        keywords = []
        for section in sections:
            if str(section.get("id") or "").lower() == "keywords":
                keywords = [part.strip() for part in re.split(r"[;,]", section.get("text") or "") if part.strip()]
        metadata = {"title": filename, "keywords": keywords}
        chapters = (
            [{"title": f"{item.get('id', '')} {item.get('title', '')}".strip(), "level": item.get("level", 1), "page": 1} for item in sections]
            or headings_from_text(text)
        )
        parsed = {
            "text": text,
            "pages": pages,
            "chapters": chapters,
            "genre": genre,
            "metadata": metadata,
            "sections": sections,
            "equations": equations,
            "figures": figures,
            "tables": tables,
            "citations": citations,
            "parse_quality": {
                "pages_ok": 1 if text.strip() else 0,
                "pages_total": 1,
                "text_len": len(text.strip()),
                "pages_ocr": 0,
            },
        }
        pipeline_step(
            "ingest",
            "parse",
            inputs={"filename": filename, "format": lower.rsplit(".", 1)[-1], "bytes": len(data)},
            result=structure_digest(parsed),
        )
        return enrich_text_inventory(parsed)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        text = data.decode("utf-8", errors="ignore")
        parsed = {
            "text": text,
            "pages": [{"page": 1, "text": text, "reading_order": "single"}],
            "chapters": headings_from_text(text),
            "genre": "generic",
            "metadata": {},
            "sections": [],
            "equations": [],
            "figures": [],
            "tables": [],
            "citations": [],
            "parse_quality": {"pages_ok": 0, "pages_total": 0, "text_len": len(text.strip()), "pages_ocr": 0},
        }
        pipeline_step(
            "ingest",
            "parse",
            inputs={"filename": filename, "format": "unknown", "bytes": len(data)},
            result={**structure_digest(parsed), "reason": "pdf_open_failed_fallback_text"},
        )
        return parsed
    parsed = parse_pdf_document(doc)
    pipeline_step(
        "ingest",
        "parse",
        inputs={"filename": filename, "format": "pdf", "bytes": len(data), "pdf_pages": len(doc)},
        result=structure_digest(parsed),
    )
    return parsed
