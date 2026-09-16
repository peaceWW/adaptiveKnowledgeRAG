from types import SimpleNamespace

from app.ingestion.catalog_sync import build_catalog_plan, catalog_needs_rebuild


def _doc(**kwargs):
    structure = kwargs.pop(
        "structure",
        {
            "metadata": {},
            "sections": [
                {"id": "I", "title": "INTRODUCTION", "page": 1},
                {"id": "II", "title": "ARCHITECTURE", "page": 2},
            ],
        },
    )
    return SimpleNamespace(
        id="doc-1",
        filename="A_10_Gb_s_Hybrid_ADC.pdf",
        index_meta={"title": "A 10 Gb/s Hybrid ADC-Based Receiver"},
        structure=structure,
        **kwargs,
    )


def _unit(**kwargs):
    data = {
        "id": "u1",
        "title": "Hybrid ADC equalization",
        "concepts": ["ADC", "FFE"],
        "source_section": "ARCHITECTURE",
        "source_chapter": "II",
        "source_page": 2,
        "semantic_role": "principle",
        "unit_meta": {"kind": "concept", "section_id": "II"},
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_catalog_plan_is_article_chapter_then_unit_leaves():
    plan = build_catalog_plan(
        _doc(),
        [
            _unit(id="u1"),
            _unit(
                id="u2",
                title="Fig. 1 Receiver",
                concepts=["ADC"],
                source_section="ARCHITECTURE",
                source_chapter="II",
                source_page=2,
                unit_meta={"kind": "figure", "section_id": "II"},
            ),
            _unit(
                id="u3",
                title="Paper background",
                concepts=[],
                source_section="INTRODUCTION",
                source_chapter="I",
                source_page=1,
                unit_meta={"kind": "concept", "section_id": "I"},
            ),
        ],
    )
    title = "A 10 Gb／s Hybrid ADC-Based Receiver"
    paths = {item["path"] for item in plan["nodes"]}
    assert title in paths
    assert f"{title}/01 I INTRODUCTION" in paths
    assert f"{title}/02 II ARCHITECTURE" in paths
    assert f"{title}/01 I INTRODUCTION/Paper background" in paths
    assert f"{title}/02 II ARCHITECTURE/Hybrid ADC equalization" in paths
    assert f"{title}/02 II ARCHITECTURE/Fig. 1 Receiver" in paths
    assert "主题/ADC" not in paths
    assert not any(path.startswith("本体/") for path in paths)
    assert plan["assignments"]["u3"].endswith("Paper background")
    assert plan["assignments"]["u1"].endswith("Hybrid ADC equalization")
    leaves = [item for item in plan["nodes"] if item["path"].count("/") == 2]
    assert {item["name"] for item in leaves} == {"Paper background", "Hybrid ADC equalization", "Fig. 1 Receiver"}


def test_catalog_rebuild_when_legacy_topic_tree_exists():
    legacy = SimpleNamespace(path="主题/ADC", related_concepts=["__auto__"])
    assert catalog_needs_rebuild([legacy], unit_count=3)
    unit_leaf = SimpleNamespace(path="paper/01 I/unit", related_concepts=["__unit__:abc"])
    assert not catalog_needs_rebuild([unit_leaf], unit_count=3)
    assert catalog_needs_rebuild([], unit_count=2)
    assert not catalog_needs_rebuild([], unit_count=0)
