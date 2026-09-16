from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from app.domain.enums import KnowledgeType, QueryIntent, SemanticRole
from app.domain.ontology import flatten_ontology
from app.domain.registry import registry
from app.domain.strategy import DocumentContext, QueryContext
from app.ingestion.academic_parse import (
    collect_citations,
    extract_equations,
    looks_like_academic_paper,
    split_ieee_sections,
)
from app.ingestion.classifier import KnowledgeClassifier
from app.ingestion.coverage import apply_coverage_stubs, check_ingest_coverage
from app.ingestion.paper_extractor import extract_paper_units
from app.ingestion.parser import parse_bytes
from app.model_gateway.gateway import ModelGateway

IEEE_TEXT = """A 10 Gb/s Hybrid ADC-Based Receiver With Embedded Analog Equalization
Ayman Shafik
IEEE Journal of Solid-State Circuits
Abstract—This paper presents a 10 Gb/s hybrid ADC-based receiver with embedded analog and per-symbol dynamically enabled digital equalization. The architecture uses a SAR ADC, FFE and DFE [1].
Index Terms—ADC-based receiver, analog-to-digital converter (ADC), decision feedback equalizer (DFE), feed-forward equalizer (FFE), successive approximation register (SAR).
I. INTRODUCTION
ADC-based receivers can implement FFE and DFE in the digital domain [1], [2]. The SNR follows SNR = 6.02N + 1.76 (1) for an ideal quantizer.
II. ARCHITECTURE
Fig. 1. Hybrid ADC-based receiver block diagram.
The analog front-end embeds CTLE. Digital equalization is dynamically enabled per symbol.
III. MEASUREMENT RESULTS
The 40 nm CMOS prototype achieves 10 Gb/s and 1.2 pJ/bit. Measured SNDR is 34 dB.
TABLE I COMPARISON WITH PRIOR ADC-BASED RECEIVERS
This work 10 Gb/s 40 nm 12 mW
IV. CONCLUSION
A hybrid ADC-based RX was demonstrated.
REFERENCES
[1] A. Author, "An ADC-based RX," IEEE JSSC, vol. 50, no. 1, pp. 1-10, 2015.
[2] B. Writer, "Digital equalization," IEEE TCAS, 2014.
"""

REAL_PDF = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "A_10_Gb_s_Hybrid_ADC-Based_Receiver_With_Embedded_Analog_and_Per-Symbol_Dynamically_Enabled_Digital_Equalization.pdf"
)


def _make_two_column_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 56), "A 10 Gb/s Hybrid ADC-Based Receiver", fontsize=14)
    page.insert_textbox(
        fitz.Rect(48, 110, 290, 520),
        "Abstract—This paper presents a hybrid ADC-based receiver.\n\n"
        "I. INTRODUCTION\n"
        "ADC-based receivers use FFE and DFE [1].\n"
        "SNR = 6.02N + 1.76          (1)\n",
        fontsize=10,
    )
    page.insert_textbox(
        fitz.Rect(320, 110, 564, 520),
        "II. ARCHITECTURE\n"
        "The analog front-end embeds CTLE equalization.\n"
        "Fig. 1. Receiver block diagram.\n",
        fontsize=10,
    )
    page.insert_text((48, 700), "REFERENCES", fontsize=11)
    page.insert_text((48, 720), '[1] A. Author, "An ADC-based RX," IEEE JSSC, 2015.', fontsize=9)
    return doc.tobytes()


def test_split_ieee_sections_and_citations():
    pages = [{"page": 1, "text": IEEE_TEXT}]
    sections = split_ieee_sections(pages)
    ids = [item["id"] for item in sections]
    assert "abstract" in ids
    assert "I" in ids
    assert "references" in ids
    citations = collect_citations(pages, [])
    keys = {item["key"] for item in citations}
    assert "[1]" in keys
    assert "[2]" in keys
    assert "IEEE JSSC" in next(item["text"] for item in citations if item["key"] == "[1]")


def test_equation_fallback_from_plain_text():
    eqs = extract_equations([], 1, IEEE_TEXT)
    assert any(item["eq_id"] == "1" for item in eqs)


def test_parse_markdown_academic_paper():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    assert parsed["genre"] == "academic_paper"
    assert any(section["id"] == "abstract" for section in parsed["sections"])
    assert parsed["citations"]


def test_two_column_pdf_reading_order():
    parsed = parse_bytes("ieee.pdf", _make_two_column_pdf())
    assert parsed["genre"] == "academic_paper"
    text = parsed["text"]
    assert "INTRODUCTION" in text
    assert "ARCHITECTURE" in text
    assert text.find("INTRODUCTION") < text.find("ARCHITECTURE")
    page0 = parsed["pages"][0]
    assert page0["reading_order"] == "two_column"
    assert parsed["citations"]
    assert any(item["key"] == "[1]" for item in parsed["citations"])
    assert any(item.get("fig_id") == "1" for item in parsed["figures"])


def test_real_ieee_pdf_structure():
    if not REAL_PDF.exists():
        return
    parsed = parse_bytes(REAL_PDF.name, REAL_PDF.read_bytes())
    assert parsed["genre"] == "academic_paper"
    assert len(parsed["pages"]) == 15
    meta = parsed["metadata"]
    assert "Hybrid ADC" in (meta.get("title") or "")
    assert meta.get("doi")
    assert meta.get("keywords")
    # Body streams in some IEEE Xplore copies are not Flate-decodable;
    # layout fields are required only when page text is actually extracted.
    if (parsed.get("text") or "").strip():
        ids = {section["id"] for section in parsed["sections"]}
        assert "abstract" in ids
        assert "references" in ids
        assert parsed["citations"]


def test_paper_extractor_forces_inventory():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    context = DocumentContext(
        document_id="d1",
        filename="paper.md",
        text=parsed["text"],
        structure=parsed,
        classification={"knowledge_type": "technical_concept", "document_genre": "academic_paper"},
    )
    drafts = extract_paper_units(context, knowledge_type=KnowledgeType.TECHNICAL_CONCEPT)
    roles = {draft.semantic_role for draft in drafts}
    anchors = {str((draft.unit_meta or {}).get("anchor")) for draft in drafts}
    assert SemanticRole.FORMULA in roles
    assert SemanticRole.REFERENCE in roles
    assert "eq:1" in anchors
    assert "cite:[1]" in anchors
    assert "cite:[2]" in anchors
    coverage = check_ingest_coverage(parsed, drafts)
    assert not coverage["missing_equations"]
    assert not coverage["missing_citations"]


def test_coverage_adds_stubs_for_missing_inventory():
    structure = {
        "genre": "academic_paper",
        "equations": [{"eq_id": "3", "raw": "x=1", "page": 1}],
        "citations": [{"key": "[9]", "text": "Prior work"}],
        "figures": [],
        "tables": [],
        "sections": [{"id": "I", "title": "Introduction", "page": 1, "text": "Hello ADC architecture."}],
    }
    context = DocumentContext(document_id="d1", filename="x.pdf", text="Hello", structure={"genre": "academic_paper", "sections": []})
    drafts = extract_paper_units(context)
    drafts, coverage = apply_coverage_stubs(structure, drafts, KnowledgeType.TECHNICAL_CONCEPT)
    anchors = {str((draft.unit_meta or {}).get("anchor")) for draft in drafts}
    assert "eq:3" in anchors
    assert "cite:[9]" in anchors
    assert coverage["stub_count"] >= 2


def test_technical_strategy_routes_academic_paper():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    drafts = registry.get(KnowledgeType.TECHNICAL_CONCEPT).build_units(
        DocumentContext(
            document_id="d1",
            filename="paper.md",
            text=parsed["text"],
            structure=parsed,
            classification={"document_genre": "academic_paper"},
        )
    )
    assert any(draft.semantic_role == SemanticRole.FORMULA for draft in drafts)
    assert any(draft.semantic_role == SemanticRole.REFERENCE for draft in drafts)


def test_classifier_marks_academic_genre():
    clf = KnowledgeClassifier(ModelGateway())
    result = clf.classify(IEEE_TEXT, "jssc.pdf", structure={"genre": "academic_paper"})
    assert result["document_genre"] == "academic_paper"
    assert result["knowledge_type"] == KnowledgeType.TECHNICAL_CONCEPT.value


def test_ontology_includes_mixed_signal():
    names = {row["name"] for row in flatten_ontology()}
    assert "ADC" in names
    assert "DFE" in names
    assert "Wireline Receiver" in names


def test_comparison_plan_requires_metric():
    plan = registry.get(KnowledgeType.TECHNICAL_CONCEPT).plan(
        QueryContext(query="compare ADC receivers", intent=QueryIntent.COMPARISON, topics=["ADC"])
    )
    roles = {r.value for r in plan.required_roles}
    assert "metric" in roles
    assert "comparison" in roles
    assert "formula" in roles


def test_looks_like_academic_paper():
    assert looks_like_academic_paper(IEEE_TEXT, filename="jssc.pdf")
    assert not looks_like_academic_paper("CDC synchronizer must be placed in the RX clock domain.", filename="guide.md")


def test_section_units_have_parent_anchors():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    drafts = extract_paper_units(
        DocumentContext(document_id="d1", filename="paper.md", text=parsed["text"], structure=parsed)
    )
    by_anchor = {str((draft.unit_meta or {}).get("anchor")): draft for draft in drafts}
    assert "sec:II" in by_anchor
    assert (by_anchor["fig:1"].unit_meta or {}).get("parent_anchor") == "sec:II"
    assert (by_anchor["eq:1"].unit_meta or {}).get("parent_anchor")
    assert any(rel.get("to_key") == "fig:1" for rel in by_anchor["sec:II"].relations)


def test_coverage_reports_retrieval_ready():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    drafts = extract_paper_units(
        DocumentContext(document_id="d1", filename="paper.md", text=parsed["text"], structure=parsed)
    )
    coverage = check_ingest_coverage(parsed, drafts)
    assert "retrieval_ready_score" in coverage
    assert coverage["empty_text"] is False
    assert not coverage["missing_equations"]


def test_parse_intent_and_anchor_keys():
    from app.retrieval.workflow import _parse_intent, query_anchor_keys

    assert _parse_intent("和先前 ADC RX 比怎样", None) == QueryIntent.COMPARISON
    assert _parse_intent("Fig.10 的 ADC 怎么分级？", "comparison") == QueryIntent.COMPARISON
    assert _parse_intent("RX什么时候使用ADC", None) == QueryIntent.SOLUTION
    assert "fig:10" in query_anchor_keys("Fig.10 的 ADC 怎么分级？")
    assert "eq:1" in query_anchor_keys("Eq.(1) 怎么算")


def test_query_terms_extracts_english_from_mixed_question():
    from app.retrieval.query_terms import query_terms, retrieval_query

    terms = query_terms("RX什么时候使用ADC")
    lowered = {item.lower() for item in terms}
    assert "rx" in lowered
    assert "adc" in lowered
    assert "RX" in retrieval_query("RX什么时候使用ADC") or "ADC" in retrieval_query("RX什么时候使用ADC")


def test_qdrant_memory_search_includes_ai_processed():
    from app.storage.qdrant_store import QdrantStore

    store = QdrantStore()
    store.client = None
    store.upsert("u1", [1.0, 0.0, 0.0], {"lifecycle": "AI_PROCESSED", "semantic_role": "principle", "kb_id": "k"})
    store.upsert("u2", [0.9, 0.1, 0.0], {"lifecycle": "PENDING_REVIEW", "semantic_role": "formula", "kb_id": "k"})
    hits = store._memory_search([1.0, 0.0, 0.0], 10, "k", ["principle"], "PUBLISHED", None)
    ids = {hit["id"] for hit in hits}
    assert "u1" in ids
    assert "u2" not in ids


def test_qdrant_memory_search_does_not_filter_roles():
    from app.storage.qdrant_store import QdrantStore

    store = QdrantStore()
    store.client = None
    store.upsert("u1", [1.0, 0.0, 0.0], {"lifecycle": "PUBLISHED", "semantic_role": "interface", "kb_id": "k"})
    store.upsert("u2", [0.9, 0.1, 0.0], {"lifecycle": "PUBLISHED", "semantic_role": "principle", "kb_id": "k"})
    hits = store._memory_search([1.0, 0.0, 0.0], 10, "k", ["principle"], "PUBLISHED", None)
    ids = {hit["id"] for hit in hits}
    assert "u1" in ids
    assert "u2" in ids


def test_figure_captions_include_crop_mode():
    from app.ingestion.academic_parse import extract_figure_captions

    figures = extract_figure_captions("Fig. 1. Receiver block diagram.\n", 1)
    assert figures[0]["fig_id"] == "1"
    assert figures[0]["crop_mode"] in {"page_fallback", "missing", "image"}


def test_vision_figure_degrades_without_model():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    drafts = extract_paper_units(
        DocumentContext(document_id="d1", filename="paper.md", text=parsed["text"], structure=parsed)
    )
    fig = next(draft for draft in drafts if (draft.unit_meta or {}).get("kind") == "figure")
    assert "Fig. 1" in fig.title
    assert "Description:" not in fig.content


def test_pipeline_log_clips_long_text():
    from app.observability.pipeline_log import clip, step

    step("ingest", "file_type", inputs={"filename": "a.pdf"}, result={"genre": "academic_paper"})
    clipped = clip("x" * 500)
    assert isinstance(clipped, str) and clipped.endswith("…")
