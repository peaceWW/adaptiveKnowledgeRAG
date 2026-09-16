"""Deterministic, versioned evaluation metrics; unknown is never a zero score."""
import hashlib
import json
import re

SCORING_VERSION = "evidence-v2"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def classify_question(question, expected_roles=None):
    text = (question or "").lower()
    for words, label in [(["对比", "比较", "区别", "vs"], "比较类"),
                         (["为什么", "原因"], "解释类"),
                         (["如何", "怎么", "解决", "推荐"], "解决方案类"),
                         (["什么是", "何为", "定义", "是什么"], "定义类")]:
        if any(word in text for word in words):
            return label
    roles = set(expected_roles or [])
    for keys, label in [({"comparison"}, "比较类"), ({"solution"}, "解决方案类"),
                        ({"root_cause", "explanation"}, "解释类"), ({"definition"}, "定义类")]:
        if roles & keys:
            return label
    return "其他"


def normalize_anchor(text):
    value = re.sub(r"\s+", "", str(text).lower())
    value = re.sub(r"^(figure|fig)[.:]?", "fig:", value)
    value = re.sub(r"^(equation|eq)[.:]?\(?", "eq:", value).rstrip(")")
    return value


def matches(label, hit):
    """Legacy labels are exact titles. Keyword matching must be explicitly requested."""
    if label.startswith("id:"):
        return label[3:] == (hit.get("id") or hit.get("knowledge_id"))
    if label.startswith("anchor:"):
        document, _, anchor = label[7:].partition("#")
        return document == hit.get("document_id") and normalize_anchor(anchor) == normalize_anchor(hit.get("anchor"))
    if label.startswith("keyword:"):
        needle = label[8:].strip().casefold()
        return bool(needle) and needle in (str(hit.get("title", "")) + "\n" + str(hit.get("content", ""))).casefold()
    return label.removeprefix("title:").strip() == str(hit.get("title") or "").strip()


def unique_hits(hits):
    seen, result = set(), []
    for hit in hits:
        key = hit.get("id") or hit.get("knowledge_id") or (hit.get("document_id"), hit.get("anchor"), hit.get("title"))
        if key not in seen:
            seen.add(key)
            result.append(hit)
    return result


def score_retrieval(case, output):
    hits = unique_hits(output.get("ranked_hits", output.get("hits")) or [])
    top = hits[:10]
    required = list(dict.fromkeys(case.get("required_knowledge") or []))
    relevant = list(dict.fromkeys(required + (case.get("optional_knowledge") or [])))
    found = [label for label in required if any(matches(label, hit) for hit in top)]
    missing = [label for label in required if label not in found]
    forbidden = [label for label in case.get("forbidden_knowledge", []) if any(matches(label, hit) for hit in unique_hits(hits + (output.get("hits") or [])))]
    rank = next((i + 1 for i, hit in enumerate(top) if any(matches(label, hit) for label in relevant)), None)
    roles = list(dict.fromkeys(case.get("expected_roles") or []))
    covered_roles = [role for role in roles if any((h.get("semantic_role") or h.get("role")) == role for h in hits)]
    recall = len(found) / len(required) if required else None
    return {
        "recall": recall,
        "precision": sum(any(matches(label, hit) for label in relevant) for hit in top) / 10 if relevant else None,
        "mrr": (1 / rank if rank else 0) if relevant else None,
        "coverage": len(covered_roles) / len(roles) if roles else None,
        "matched": found, "missing": missing, "forbidden": forbidden,
        "missing_roles": [r for r in roles if r not in covered_roles],
        "pass": (recall >= .8 and not forbidden) if recall is not None else None,
        "hit_count": len(hits),
        "warnings": (["未标注必需证据，召回率与检索通过率不评分"] if not required else []) +
                    (["含标题标注，建议改用 id:知识单元ID 或 anchor:文档ID#锚点"] if any(not x.startswith(("id:", "anchor:", "keyword:")) for x in relevant) else []),
    }


def check_presentation(case, output):
    answer = output.get("answer") or ""
    citations = output.get("citations") or []
    expected = (case.get("evaluation_config") or {}).get("expected_kinds") or []
    markers = re.findall(r"\[\[figure:([^\]]+)\]\]", answer)
    by_id = {c.get("knowledge_id") or c.get("id"): c for c in citations}
    images = []
    for marker in dict.fromkeys(markers):
        cite = by_id.get(marker)
        images.append({"id": marker, "resolved": bool(cite and (cite.get("image_key") or cite.get("image_url"))),
                       "document_id": (cite or {}).get("document_id"), "image_key": (cite or {}).get("image_key"),
                       "available": None})
    # Legacy Markdown images are checked against retrieved references, not fetched from model-generated URLs.
    for cite in citations:
        url = cite.get("image_url")
        if url and re.search(r"!\[[^\]]*\]\(<?" + re.escape(url) + r">?\)", answer):
            if not any(i["id"] == cite.get("knowledge_id") for i in images):
                images.append({"id": cite.get("knowledge_id"), "resolved": True, "document_id": cite.get("document_id"), "image_key": cite.get("image_key"), "available": None})
    has_math = bool(re.search(r"\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+\$", answer))
    missing = []
    if "figure" in expected and not images:
        missing.append("回答未插入图片")
    if "equation" in expected and not has_math:
        missing.append("回答未包含公式排版")
    if "text" in expected and not answer.strip():
        missing.append("回答为空")
    if "table" in expected and not re.search(r"\|\s*:?-{3,}", answer):
        missing.append("回答未包含表格")
    return {"images": images, "has_math": has_math, "missing": missing,
            "scope": "检查正文图片引用、存储资源和公式标记；公式数学正确性与图文一致性仍需答案评审。"}


def average(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def aggregate(details):
    completed = [d for d in details if d.get("status") == "completed"]
    metrics = {key: average([d.get(key) for d in completed]) for key in ("recall", "precision", "mrr", "coverage")}
    metrics.update({key: average([(d.get("judge") or {}).get(key) for d in completed]) for key in ("correctness", "groundedness", "completeness")})
    metrics.update({"pass_rate": average([d.get("pass") for d in completed]),
                    "forbidden_hits": sum(len(d.get("forbidden", [])) for d in completed),
                    "cases": len(details), "completed": len(completed),
                    "errors": sum(d.get("status") == "error" for d in details),
                    "judged": sum((d.get("judge") or {}).get("status") == "scored" for d in completed),
                    "scored_cases": sum(d.get("recall") is not None for d in completed),
                    "elapsed_ms": sum(d.get("elapsed_ms", 0) for d in details)})
    return metrics
