# 把策略中心配置落到抽取：提取内容开关与文本拆分方式分开，并按文档保存快照。
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import re

from app.domain.enums import KnowledgeType, SemanticRole
from app.domain.extraction_policy import EXTRACTION_KINDS, extraction_kind, normalized_policy
from app.domain.strategy import DocumentContext, KnowledgeUnitDraft
from app.ingestion.coverage import REQUIRED_ROLES
from app.ingestion.extractor import _extract_concepts, _infer_role, extract_units_from_text
from app.ingestion.paper_extractor import _inventory_units, extract_paper_units
from app.observability.pipeline_log import draft_digest, step as pipeline_step


def strategy_snapshot(strategy, roles=()) -> dict:
    """确认策略时冻结一份配置，后续改策略中心不影响已抽文档。"""
    selected = set(strategy.roles or [])
    return {
        "id": strategy.id,
        "name": strategy.name,
        "version": strategy.version,
        "knowledge_type": strategy.knowledge_type,
        "roles": list(strategy.roles or []),
        "chunk_policy": strategy.chunk_policy,
        "extraction_policy": normalized_policy(strategy.extraction_policy),
        "completeness_policy": deepcopy(strategy.completeness_policy or {}),
        "role_rules": [
            {"key": role.key, "label": role.label, "keywords": list(role.keywords or [])}
            for role in roles
            if role.key in selected
        ],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def effective_snapshot(structure: dict | None, knowledge_type: str, fallback_roles: list[str] | None = None) -> dict:
    """优先用文档上冻结的快照；无快照时用 process_config 拼一份，避免抽取再走未配置路径。"""
    process = (structure or {}).get("process_config") or {}
    snapshot = process.get("strategy_snapshot")
    if snapshot:
        result = dict(snapshot)
        result["extraction_policy"] = normalized_policy(result.get("extraction_policy"))
        result.setdefault("chunk_policy", process.get("chunk_policy") or "semantic_unit")
        result.setdefault("knowledge_type", knowledge_type)
        return result
    return {
        "id": "",
        "name": "inline",
        "knowledge_type": knowledge_type,
        "roles": list(fallback_roles or []),
        "chunk_policy": process.get("chunk_policy") or "semantic_unit",
        "extraction_policy": normalized_policy(process.get("extraction_policy")),
        "completeness_policy": process.get("completeness_policy") or {"minimum_coverage": 0.9},
        "role_rules": [],
    }


def scoped_structure(structure: dict, snapshot: dict) -> dict:
    """覆盖率只检查本次启用的内容：关掉的图/表/公式不进入 missing 清单。"""
    result = deepcopy(structure)
    policy = normalized_policy(snapshot.get("extraction_policy"))
    for inventory, key in [
        ("equations", "formulas"),
        ("figures", "images"),
        ("tables", "tables"),
        ("citations", "references"),
    ]:
        if not policy[key]:
            result[inventory] = []
    required = set(snapshot.get("roles") or []) & set(REQUIRED_ROLES) if policy["text"] else set()
    required -= {"formula", "reference"}
    if policy["formulas"] and result.get("equations"):
        required.add("formula")
    if policy["references"] and result.get("citations"):
        required.add("reference")
    result["required_roles"] = sorted(required)
    result["coverage_threshold"] = (snapshot.get("completeness_policy") or {}).get("minimum_coverage", 0.9)
    return result


def build_configured_units(context: DocumentContext, snapshot: dict) -> list[KnowledgeUnitDraft]:
    """文本按 chunk_policy 拆分；公式/图/表/引用只看 extraction_policy 开关，不依赖文本 Role。"""
    policy = normalized_policy(snapshot.get("extraction_policy"))
    context = replace(context, extraction_policy=policy)
    knowledge_type = KnowledgeType(snapshot.get("knowledge_type") or KnowledgeType.TECHNICAL_CONCEPT.value)
    keys = set(snapshot.get("roles") or []) - {"formula", "reference"}
    native_roles = {role for role in SemanticRole if role.value in keys}
    text_roles = native_roles or {SemanticRole.EXPLANATION}
    chunk_policy = snapshot.get("chunk_policy") or "semantic_unit"
    academic = (context.structure or {}).get("genre") == "academic_paper"
    drafts: list[KnowledgeUnitDraft] = []
    text_source = "skipped"
    has_model = bool(getattr(getattr(context, "gateway", None), "client", None))
    if policy["text"]:
        # 有模型时按快照 Role 抽；失败则去掉 gateway 再走启发式，避免论文路径再打一遍写死 Prompt 的 LLM
        if has_model:
            from app.ingestion.role_extractor import extract_role_units

            drafts = extract_role_units(context, snapshot, knowledge_type)
            if drafts:
                text_source = "role_llm"
        if not drafts:
            heuristic_ctx = replace(context, gateway=None) if has_model else context
            if chunk_policy == "semantic_unit" and academic:
                drafts = extract_paper_units(heuristic_ctx, text_roles, knowledge_type)
                text_source = "paper_semantic"
            elif chunk_policy == "semantic_unit":
                drafts = extract_units_from_text(heuristic_ctx, text_roles, knowledge_type)
                text_source = "paragraph_semantic"
            else:
                drafts = _structured_text_units(heuristic_ctx, text_roles, knowledge_type, chunk_policy)
                text_source = chunk_policy
    existing = {str((draft.unit_meta or {}).get("anchor") or "") for draft in drafts}
    # 论文语义抽已含清单；其它拆分路径必须单独补图/表，且不要求用户勾选 METRIC 等文本类别
    if text_source != "paper_semantic":
        for draft in _inventory_units(context, knowledge_type, set()):
            if str((draft.unit_meta or {}).get("anchor") or "") not in existing:
                drafts.append(draft)

    kind_to_policy = {item["key"]: item["policy_key"] for item in EXTRACTION_KINDS}
    custom_rules = [
        rule
        for rule in snapshot.get("role_rules") or []
        if rule.get("key") in keys and rule.get("key") not in {r.value for r in SemanticRole}
    ]
    result: list[KnowledgeUnitDraft] = []
    for draft in drafts:
        kind = extraction_kind(draft)
        policy_key = kind_to_policy.get(kind, "text")
        if not policy.get(policy_key, True):
            continue
        if kind == "text":
            custom = [
                rule["key"]
                for rule in custom_rules
                if any(str(word).lower() in draft.content.lower() for word in rule.get("keywords") or [] if str(word).strip())
            ]
            meta_custom = list((draft.unit_meta or {}).get("custom_roles") or [])
            if draft.semantic_role not in native_roles and not custom and not meta_custom:
                continue
            if custom or meta_custom:
                draft.unit_meta = {
                    **(draft.unit_meta or {}),
                    "custom_roles": list(dict.fromkeys(meta_custom + custom)),
                }
            # 千问已按窗口抽取并带原文 source_span，不再按 chunk_size 切开以免丢失对照片段
            if (draft.unit_meta or {}).get("extraction_source") == "role_llm":
                result.append(
                    replace(
                        draft,
                        unit_meta={
                            **(draft.unit_meta or {}),
                            "chunk_policy": chunk_policy,
                            "strategy_id": snapshot.get("id"),
                            "extraction_kind": kind,
                        },
                    )
                )
                continue
            overlap = policy["chunk_overlap"] if chunk_policy == "fixed_token" else 0
            parts = split_content(draft.content, policy["chunk_size"], overlap)
            for index, part in enumerate(parts):
                meta = {
                    **(draft.unit_meta or {}),
                    "chunk_policy": chunk_policy,
                    "part": index + 1,
                    "parts": len(parts),
                    "strategy_id": snapshot.get("id"),
                    "extraction_kind": kind,
                }
                anchor = meta.get("anchor")
                if anchor and index:
                    meta.update(anchor=f"{anchor}:part{index + 1}", parent_anchor=anchor)
                title = draft.title
                if len(parts) > 1:
                    title = f"{draft.title[:160]}（{index + 1}/{len(parts)}）"
                result.append(
                    replace(
                        draft,
                        content=part,
                        source_span=part[:500],
                        title=title,
                        unit_meta=meta,
                    )
                )
        else:
            draft.unit_meta = {
                **(draft.unit_meta or {}),
                "strategy_id": snapshot.get("id"),
                "extraction_kind": kind,
                "formula_mode": policy.get("formula_mode"),
                "image_mode": policy.get("image_mode"),
                "table_mode": policy.get("table_mode"),
            }
            result.append(draft)
    pipeline_step(
        "ingest",
        "configured_extract",
        inputs={
            "filename": context.filename,
            "chunk_policy": chunk_policy,
            "extraction_policy": {key: policy[key] for key in ("text", "formulas", "images", "tables", "references")},
            "formula_mode": policy["formula_mode"],
            "image_mode": policy["image_mode"],
            "table_mode": policy["table_mode"],
            "chunk_size": policy["chunk_size"],
            "roles": sorted(keys),
        },
        result={"text_source": text_source, **draft_digest(result)},
    )
    return result


def split_content(text: str, size: int, overlap: int = 0) -> list[str]:
    """按字符上限切文本；图/公式/表不走这里。overlap 仅 fixed_token 使用。"""
    if not text.strip():
        return []
    if len(text) <= size:
        return [text.strip()]
    step = max(size - max(overlap, 0), 1)
    result = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        result.append(text[start:end].strip())
        if end == len(text):
            break
        start += step
    return [part for part in result if part]


def _structured_text_units(context, allowed, knowledge_type, chunk_policy):
    """按章节或整页产出文本块，超长由 split_content 再切；公式图片保持独立 unit。"""
    sections = context.structure.get("sections") or []
    if chunk_policy == "section" and sections:
        records = [
            {
                "page": item.get("page", 1),
                "text": item.get("text") or "",
                "title": item.get("title") or item.get("id"),
                "anchor": f"sec:{item.get('id')}",
            }
            for item in sections
        ]
    else:
        records = []
        for page in context.structure.get("pages") or [{"page": 1, "text": context.text}]:
            text = page.get("text") or ""
            if chunk_policy == "section":
                pieces = re.split(
                    r"(?m)(?=^#{1,6}\s+|^第[一二三四五六七八九十\d]+[章节]\s*|^\d+(?:\.\d+)*[.、 ]\s*\S)",
                    text,
                )
            else:
                pieces = [text]
            for index, piece in enumerate(pieces):
                if piece.strip():
                    records.append(
                        {
                            "page": page.get("page", 1),
                            "text": piece,
                            "title": piece.strip().splitlines()[0][:140],
                            "anchor": f"text:p{page.get('page', 1)}:{index}",
                        }
                    )
    result = []
    for record in records:
        text = record["text"].strip()
        if not text:
            continue
        result.append(
            KnowledgeUnitDraft(
                title=str(record.get("title") or context.filename)[:180],
                content=text,
                semantic_role=_infer_role(text, allowed),
                knowledge_type=knowledge_type,
                concepts=_extract_concepts(text),
                source_span=text[:500],
                source_page=int(record["page"]),
                source_section=str(record.get("title") or "")[:64],
                parent_context=context.filename,
                unit_meta={"kind": "section" if chunk_policy == "section" else "text", "anchor": record["anchor"]},
            )
        )
    return result
