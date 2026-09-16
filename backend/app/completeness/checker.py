from __future__ import annotations

from app.domain.strategy import CompletenessResult, QueryContext
from app.model_gateway.gateway import ModelGateway
from app.prompts.loader import load_prompt

DEFAULT_PROMPT = """你是芯片设计工程师，检查检索覆盖。不得补知识。输出 JSON：
{"required_knowledge":[],"covered":[],"missing":[],"completeness_score":0.0,"need_secondary_retrieval":false,"secondary_query":""}
"""


class CompletenessChecker:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def check(
        self,
        query: QueryContext,
        required: list[str],
        retrieved_titles: list[str],
        retrieved_roles: list[str],
        threshold: float = 0.8,
        retrieved_kinds: list[str] | None = None,
    ) -> CompletenessResult:
        """覆盖检查：把已命中 kind 交给模型，架构问才能判断缺不缺图。"""
        llm = self.gateway.chat_json(
            load_prompt("completeness-checker", DEFAULT_PROMPT),
            str(
                {
                    "query": query.query,
                    "required": required,
                    "retrieved_titles": retrieved_titles,
                    "retrieved_roles": retrieved_roles,
                    "retrieved_kinds": retrieved_kinds or [],
                    "required_kinds": list(query.evidence_types or []),
                }
            ),
        )
        if llm.get("required_knowledge"):
            score = float(llm.get("completeness_score") or 0)
            return CompletenessResult(
                required_knowledge=llm.get("required_knowledge") or required,
                covered=llm.get("covered") or [],
                missing=llm.get("missing") or [],
                completeness_score=score,
                need_secondary_retrieval=bool(llm.get("need_secondary_retrieval")) or score < threshold,
                secondary_query=llm.get("secondary_query") or "",
            )
        covered = [role for role in required if role in retrieved_roles]
        missing = [role for role in required if role not in covered]
        score = len(covered) / max(len(required), 1)
        return CompletenessResult(
            required_knowledge=required,
            covered=covered,
            missing=missing,
            completeness_score=round(score, 2),
            need_secondary_retrieval=score < threshold,
            secondary_query=" ".join(query.topics + missing),
        )
