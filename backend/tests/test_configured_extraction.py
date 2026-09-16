from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.extraction_policy import normalized_policy
from app.domain.strategy import DocumentContext
from app.ingestion.configured_extraction import build_configured_units, scoped_structure, split_content
from app.ingestion.parser import parse_bytes
from app.ingestion.paper_extractor import extract_paper_units

IEEE_TEXT = """A 10 Gb/s Hybrid ADC-Based Receiver
IEEE Journal of Solid-State Circuits
Abstract—This paper presents a hybrid ADC-based receiver [1].
Index Terms—ADC-based receiver, DFE, FFE.
I. INTRODUCTION
ADC-based receivers can implement FFE and DFE. SNR = 6.02N + 1.76 (1).
II. ARCHITECTURE
Fig. 1. Receiver block diagram of the hybrid ADC.
TABLE I. Measured performance summary
SNDR 34 dB
References
[1] A. Prior, “Earlier ADC,” IEEE JSSC, 2014.
"""


def _paper_context(policy=None, roles=None):
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    snapshot = {
        "id": "s1",
        "name": "Technical Knowledge V1",
        "knowledge_type": KnowledgeType.TECHNICAL_CONCEPT.value,
        "roles": roles or ["definition", "principle", "summary"],
        "chunk_policy": "semantic_unit",
        "extraction_policy": normalized_policy(policy),
        "completeness_policy": {"minimum_coverage": 0.9},
        "role_rules": [],
    }
    context = DocumentContext(
        document_id="d1",
        filename="paper.md",
        text=parsed["text"],
        structure=scoped_structure(parsed, snapshot),
        extraction_policy=snapshot["extraction_policy"],
    )
    return context, snapshot


def _kinds(drafts):
    return {(draft.unit_meta or {}).get("kind") for draft in drafts}


def test_images_and_tables_are_independent_of_text_roles():
    context, snapshot = _paper_context(
        policy={"text": False, "formulas": False, "images": True, "tables": True, "references": False},
        roles=["definition"],
    )
    drafts = build_configured_units(context, snapshot)
    kinds = _kinds(drafts)
    assert "figure" in kinds
    assert "table" in kinds
    assert "section" not in kinds
    assert "equation" not in kinds
    assert "citation" not in kinds


def test_disabled_images_skip_figure_units():
    context, snapshot = _paper_context(policy={"images": False, "tables": True, "formulas": True, "text": True})
    drafts = build_configured_units(context, snapshot)
    assert "figure" not in _kinds(drafts)
    assert any((draft.unit_meta or {}).get("kind") == "equation" for draft in drafts)


def test_section_chunk_keeps_inventory_separate():
    context, snapshot = _paper_context()
    snapshot["chunk_policy"] = "section"
    drafts = build_configured_units(context, snapshot)
    kinds = _kinds(drafts)
    assert "section" in kinds or any(draft.source_chapter for draft in drafts)
    assert "figure" in kinds
    assert "equation" in kinds


def test_scoped_structure_hides_disabled_inventory():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    scoped = scoped_structure(
        parsed,
        {"roles": ["principle"], "extraction_policy": normalized_policy({"images": False, "tables": False})},
    )
    assert scoped["figures"] == []
    assert scoped["tables"] == []
    assert scoped["equations"]


def test_split_content_respects_size_and_overlap():
    parts = split_content("abcdefghij", size=4, overlap=1)
    assert parts[0] == "abcd"
    assert parts[-1].endswith("j")
    assert all(len(part) <= 4 for part in parts[:-1])


def test_extract_paper_units_without_metric_role_still_keeps_tables():
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    drafts = extract_paper_units(
        DocumentContext(
            document_id="d1",
            filename="paper.md",
            text=parsed["text"],
            structure=parsed,
            extraction_policy=normalized_policy({"tables": True, "images": True}),
        ),
        allowed_roles={SemanticRole.DEFINITION},
        knowledge_type=KnowledgeType.TECHNICAL_CONCEPT,
    )
    kinds = _kinds(drafts)
    assert "table" in kinds
    assert "figure" in kinds
