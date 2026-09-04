from __future__ import annotations

from app.domain.strategy import CompletenessResult, QueryContext
from app.model_gateway.gateway import ModelGateway


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
    ) -> CompletenessResult:
        llm = self.gateway.chat_json(
            """你不是回答生成器。判断当前检索结果是否足以完整回答用户问题。
输出 JSON：
{"required_knowledge":[],"covered":[],"missing":[],"completeness_score":0.0,"need_secondary_retrieval":false,"secondary_query":""}
不得自行补充知识。""",
            str(
                {
                    "query": query.query,
                    "required": required,
                    "retrieved_titles": retrieved_titles,
                    "retrieved_roles": retrieved_roles,
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
