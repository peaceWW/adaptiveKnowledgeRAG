from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import KnowledgeUnit, RetrievalPlannerConfig


class RetrievalPlanner:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_steps(self, query_type: str) -> list[dict]:
        result = await self.session.execute(
            select(RetrievalPlannerConfig).where(RetrievalPlannerConfig.query_type == query_type)
        )
        config = result.scalar_one_or_none()
        if config:
            return list(config.steps or [])
        return [
            {"type": "query_analyze"},
            {"type": "catalog_route"},
            {"type": "hybrid_search"},
            {"type": "rerank"},
            {"type": "completeness_check"},
        ]
