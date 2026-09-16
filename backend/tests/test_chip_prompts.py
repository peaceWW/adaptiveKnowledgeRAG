# 芯片设计提示词包：YAML 可加载、可覆盖，且都站在设计工程师视角。
from app.prompts.loader import apply_prompt_override, iter_prompt_files, load_prompt


REQUIRED_IDS = {
    "knowledge-classifier",
    "role-extractor",
    "technical-extractor",
    "figure-interpreter",
    "document-indexer",
    "query-understanding",
    "retrieval-planner",
    "completeness-checker",
    "answer-generator",
}


def test_all_prompts_are_chip_design_persona():
    rows = iter_prompt_files()
    ids = {row["prompt_id"] for row in rows}
    assert REQUIRED_IDS <= ids
    for row in rows:
        blob = row["content"]
        assert "芯片设计" in blob
        assert "{{" not in blob or row["prompt_id"] == "role-extractor"
        apply_prompt_override(row["prompt_id"], "")
        loaded = load_prompt(row["prompt_id"])
        assert loaded.strip()
        assert "芯片设计" in loaded


def test_prompt_override_wins_over_yaml():
    apply_prompt_override("answer-generator", "OVERRIDE_CHIP_PROMPT")
    assert load_prompt("answer-generator") == "OVERRIDE_CHIP_PROMPT"
    apply_prompt_override("answer-generator", "")
    assert "芯片设计" in load_prompt("answer-generator")
