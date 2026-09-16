# 架构类问答：图必须排在公式和说明前面；CDC 等非架构问不得因缺图失败。
from app.retrieval.evidence_order import (
    adjust_figure_completeness,
    cap_evidence_hits,
    evidence_label,
    evidence_priority,
    is_architecture_query,
    normalize_kind,
    order_context_hits,
    split_missing_roles_and_kinds,
)


def test_formula_query_puts_equation_before_figure():
    from app.retrieval.evidence_order import infer_evidence_types, is_formula_query, order_context_hits

    assert is_formula_query("三抽头 FFE 系数")
    assert infer_evidence_types("三抽头 FFE 系数")[0] == "equation"
    hits = [
        {"id": "abs", "kind": "concept", "score": 0.99, "title": "摘要"},
        {"id": "fig9", "kind": "figure", "score": 0.8, "title": "Fig.9 FFE circuit"},
        {"id": "eq", "kind": "equation", "score": 0.4, "title": "Eq.(3) tap coefficients"},
    ]
    ordered = order_context_hits(hits, "三抽头 FFE 系数", "definition")
    assert [item["id"] for item in ordered] == ["eq", "fig9", "abs"]


def test_hybrid_receiver_without_fig_word_still_architecture():
    from app.retrieval.evidence_order import infer_evidence_types, is_architecture_query

    assert is_architecture_query("混合接收机")
    assert infer_evidence_types("混合接收机")[0] == "figure"
    assert is_architecture_query("混合接收机架构")
    assert is_architecture_query("hybrid receiver architecture")
    assert is_architecture_query("RX 前端电路框图")
    assert not is_architecture_query("如何解决 CDC 中的亚稳态问题？")
    assert not is_architecture_query("ENOB 指标是多少")
    assert not is_architecture_query("ADC 功耗")


def test_order_puts_figure_first_for_architecture():
    hits = [
        {"id": "t", "kind": "concept", "score": 0.99, "title": "原理说明", "via": "rerank"},
        {"id": "f", "kind": "figure", "score": 0.4, "title": "Fig.4 ADC with embedded 3-tap FFE", "via": "relation"},
        {"id": "e", "kind": "equation", "score": 0.5, "title": "Eq.(1)", "via": "relation"},
    ]
    ordered = order_context_hits(hits, "混合接收机架构", "definition")
    assert [item["id"] for item in ordered] == ["f", "e", "t"]
    assert evidence_label(normalize_kind(ordered[0])) == "【图】"
    assert evidence_label(normalize_kind(ordered[1])) == "【公式】"
    assert evidence_label(normalize_kind(ordered[2])) == "【说明】"


def test_image_key_without_kind_counts_as_figure():
    hits = [
        {"id": "text", "kind": "", "score": 0.9, "title": "文字"},
        {"id": "fig", "kind": "", "score": 0.2, "title": "Fig.4", "image_key": "images/d/fig4.png"},
    ]
    ordered = order_context_hits(hits, "混合接收机架构")
    assert ordered[0]["id"] == "fig"


def test_definition_intent_uses_architecture_weights():
    weights = evidence_priority("什么是 SAR", "definition")
    assert weights["figure"] == 3.0 and weights["equation"] == 2.0


def test_architecture_completeness_requires_figure():
    missing, need, query = adjust_figure_completeness(
        "混合接收机架构",
        [{"id": "t", "kind": "concept", "source_chapter": "Architecture"}],
        [],
        False,
        "",
    )
    assert "figure" in missing and need is True
    assert "Fig" in query and "Architecture" in query


def test_cdc_markdown_does_not_fail_for_missing_figure():
    missing, need, _ = adjust_figure_completeness(
        "如何解决 CDC 中的亚稳态问题？",
        [{"id": "t", "kind": "concept"}],
        ["figure", "constraint"],
        True,
        "CDC figure",
    )
    assert "figure" not in missing
    assert missing == ["constraint"]
    assert need is True


def test_cdc_only_figure_gap_clears_secondary():
    missing, need, _ = adjust_figure_completeness(
        "CDC 亚稳态",
        [{"id": "t", "kind": "concept"}],
        ["figure"],
        True,
        "x",
    )
    assert missing == [] and need is False


def test_cap_keeps_figures_and_equations():
    hits = [{"id": f"f{i}", "kind": "figure", "score": 1} for i in range(5)]
    hits += [{"id": f"e{i}", "kind": "equation", "score": 1} for i in range(6)]
    hits += [{"id": f"t{i}", "kind": "concept", "score": 1} for i in range(10)]
    capped = cap_evidence_hits(hits)
    assert [normalize_kind(item) for item in capped].count("figure") == 3
    assert [normalize_kind(item) for item in capped].count("equation") == 4
    assert [normalize_kind(item) for item in capped].count("text") == 6
    assert capped[0]["kind"] == "figure"


def test_secondary_missing_splits_figure_from_roles():
    roles, kinds = split_missing_roles_and_kinds(["figure", "constraint", "principle"])
    assert kinds == ["figure"]
    assert roles == ["constraint", "principle"]
