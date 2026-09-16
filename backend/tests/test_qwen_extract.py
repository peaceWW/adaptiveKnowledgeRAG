from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.extraction_policy import normalized_policy
from app.domain.strategy import DocumentContext
from app.ingestion.configured_extraction import build_configured_units, scoped_structure
from app.ingestion.doc_annotator import annotate_document_index
from app.ingestion.parser import parse_bytes
from app.ingestion.role_extractor import extract_role_units
from app.model_gateway.gateway import parse_json_content
from app.retrieval.doc_index import merge_keyword_lists, should_fill_keywords, should_fill_meta

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


class FakeGateway:
    """测试用网关：假装有真实 client，记录 Prompt，按预设 JSON 返回。"""

    def __init__(self, payload=None):
        self.client = object()
        self.calls = []
        self.payload = payload if payload is not None else {"units": []}

    def chat_json(self, system, user, temperature=0.1):
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        if callable(self.payload):
            return self.payload(system, user)
        return dict(self.payload)


def _snapshot(**overrides):
    snapshot = {
        "id": "s1",
        "name": "Technical Knowledge V1",
        "knowledge_type": KnowledgeType.TECHNICAL_CONCEPT.value,
        "roles": ["definition", "principle", "summary"],
        "chunk_policy": "semantic_unit",
        "extraction_policy": normalized_policy({"text": True, "images": True, "tables": True, "formulas": True}),
        "completeness_policy": {"minimum_coverage": 0.9},
        "role_rules": [
            {"key": "principle", "label": "技术原理", "keywords": ["architecture", "FFE"]},
            {"key": "cdc_rule", "label": "CDC 规则", "keywords": ["synchronizer"]},
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _context(gateway=None, snapshot=None):
    parsed = parse_bytes("paper.md", IEEE_TEXT.encode("utf-8"))
    snap = snapshot or _snapshot()
    return DocumentContext(
        document_id="d1",
        filename="paper.md",
        text=parsed["text"],
        structure=scoped_structure(parsed, snap),
        extraction_policy=snap["extraction_policy"],
        gateway=gateway,
    ), snap


def test_parse_json_content_strips_markdown_and_prose():
    data = parse_json_content("好的，如下：\n```json\n{\"units\":[{\"title\":\"A\"}]}\n```\n以上。")
    assert data["units"][0]["title"] == "A"
    assert parse_json_content("not json") == {}
    assert parse_json_content('["list"]') == {}


def test_role_extractor_injects_snapshot_roles_into_prompt():
    span = "ADC-based receivers can implement FFE and DFE."

    def payload(system, user):
        if span not in user:
            return {"units": []}
        return {
            "units": [
                {
                    "title": "Hybrid ADC equalization",
                    "semantic_role": "principle",
                    "content": "接收机可用 FFE 与 DFE 做均衡。",
                    "source_span": span,
                    "concepts": ["FFE", "DFE"],
                    "importance": "core",
                }
            ]
        }

    gateway = FakeGateway(payload)
    context, snapshot = _context(gateway)
    drafts = extract_role_units(context, snapshot, KnowledgeType.TECHNICAL_CONCEPT)
    assert drafts
    assert drafts[0].semantic_role == SemanticRole.PRINCIPLE
    assert any(draft.source_span == span for draft in drafts)
    assert (drafts[0].unit_meta or {}).get("extraction_source") == "role_llm"
    prompt = gateway.calls[0]["system"]
    assert "principle" in prompt
    assert "技术原理" in prompt
    assert "FFE" in prompt


def test_custom_role_is_stored_in_unit_meta():
    def payload(system, user):
        if "ADC-based receivers can implement FFE and DFE." not in user:
            return {"units": []}
        return {
            "units": [
                {
                    "title": "CDC 同步",
                    "semantic_role": "cdc_rule",
                    "content": "Synchronizer 必须放在接收时钟域。",
                    "source_span": "ADC-based receivers can implement FFE and DFE.",
                    "concepts": ["Synchronizer"],
                }
            ]
        }

    gateway = FakeGateway(payload)
    snapshot = _snapshot(roles=["cdc_rule", "principle"])
    context, snapshot = _context(gateway, snapshot)
    drafts = extract_role_units(context, snapshot, KnowledgeType.TECHNICAL_CONCEPT)
    assert drafts
    assert drafts[0].semantic_role in {SemanticRole.EXPLANATION, SemanticRole.PRINCIPLE}
    assert "cdc_rule" in (drafts[0].unit_meta or {}).get("custom_roles", [])


def test_role_llm_keeps_inventory_and_skips_heuristic_when_model_returns_units():
    span = "ADC-based receivers can implement FFE and DFE."

    def payload(system, user):
        if span not in user:
            return {"units": []}
        return {
            "units": [
                {
                    "title": "Equalization",
                    "semantic_role": "principle",
                    "content": "ADC 接收机可实现 FFE 和 DFE。",
                    "source_span": span,
                    "concepts": ["ADC"],
                }
            ]
        }

    gateway = FakeGateway(payload)
    context, snapshot = _context(gateway)
    drafts = build_configured_units(context, snapshot)
    kinds = {(draft.unit_meta or {}).get("kind") for draft in drafts}
    assert any((draft.unit_meta or {}).get("extraction_source") == "role_llm" for draft in drafts)
    assert any(draft.source_span == span for draft in drafts)
    assert "figure" in kinds
    assert "table" in kinds


def test_no_model_falls_back_to_heuristic():
    context, snapshot = _context(gateway=None)
    drafts = build_configured_units(context, snapshot)
    assert drafts
    assert not any((draft.unit_meta or {}).get("extraction_source") == "role_llm" for draft in drafts)


def test_empty_llm_json_falls_back_to_heuristic():
    gateway = FakeGateway({})
    context, snapshot = _context(gateway)
    drafts = build_configured_units(context, snapshot)
    assert drafts
    assert not any((draft.unit_meta or {}).get("extraction_source") == "role_llm" for draft in drafts)
    assert gateway.calls


def test_document_annotator_writes_llm_keywords():
    gateway = FakeGateway(
        {
            "title": "Hybrid ADC Receiver",
            "authors": ["Someone"],
            "year": "2014",
            "venue": "JSSC",
            "domain": "semiconductor",
            "summary": "A hybrid ADC-based receiver with FFE/DFE.",
            "knowledge_type": "technical_concept",
            "keywords": [{"keyword": "hybrid ADC", "weight": 0.9}, "DFE"],
        }
    )
    meta, keywords = annotate_document_index(gateway, "paper.pdf", IEEE_TEXT, {"title": "old"})
    assert meta["annotated_by"] == "llm"
    assert meta["title"] == "Hybrid ADC Receiver"
    sources = {item["source"] for item in keywords}
    assert sources == {"llm"}
    assert "hybrid ADC" in {item["keyword"] for item in keywords}


def test_no_model_annotator_is_noop():
    meta, keywords = annotate_document_index(None, "paper.pdf", IEEE_TEXT, {})
    assert meta == {}
    assert keywords == []


def test_llm_keywords_are_not_overwritten_on_force_reindex():
    llm = [{"keyword": "hybrid ADC", "weight": 1.0, "source": "llm"}]
    manual = [{"keyword": "keep-me", "weight": 1.0, "source": "manual"}]
    merged = merge_keyword_lists(llm, [{"keyword": "SNDR", "weight": 0.8, "source": "extracted"}], manual)
    assert merged[0]["keyword"] == "keep-me"
    assert {item["keyword"]: item["source"] for item in merged}["hybrid ADC"] == "llm"
    assert not should_fill_keywords(llm, llm, force=True)
    assert not should_fill_keywords(manual, manual, force=True)
    assert should_fill_keywords(None, [], force=False)
    assert not should_fill_meta({"title": "A", "annotated_by": "llm"}, {"title": "A", "annotated_by": "llm"}, force=True)
    assert should_fill_meta(None, {}, force=False)


def test_embed_splits_batches_for_dashscope_limit():
    """千问 embedding 单次最多 10 条；超过时必须切批，否则整篇入库会退回 hash 向量。"""
    from types import SimpleNamespace

    from app.model_gateway.gateway import ModelGateway

    gw = ModelGateway()
    calls: list[int] = []

    class _Embeddings:
        def create(self, model, input):
            assert len(input) <= 10
            calls.append(len(input))
            return SimpleNamespace(
                data=[SimpleNamespace(index=i, embedding=[float(i)]) for i, _ in enumerate(input)]
            )

    gw.client = SimpleNamespace(embeddings=_Embeddings())
    gw.settings = SimpleNamespace(model_embedding="text-embedding-v3", embedding_batch_size=10)
    vectors = gw.embed([f"t{i}" for i in range(25)])
    assert calls == [10, 10, 5]
    assert len(vectors) == 25
    assert gw.embed([]) == []
