from app.domain.enums import KnowledgeType, QueryIntent
from app.domain.registry import registry
from app.domain.strategy import QueryContext


def test_registry_has_phase1_strategies():
    assert registry.get(KnowledgeType.TECHNICAL_CONCEPT).type() == KnowledgeType.TECHNICAL_CONCEPT
    assert registry.get(KnowledgeType.INCIDENT_CASE).type() == KnowledgeType.INCIDENT_CASE
    assert registry.get(KnowledgeType.API_DOCUMENT).type() == KnowledgeType.API_DOCUMENT


def test_solution_plan_requires_constraint():
    plan = registry.get(KnowledgeType.TECHNICAL_CONCEPT).plan(
        QueryContext(query="如何解决 CDC", intent=QueryIntent.SOLUTION, topics=["CDC"])
    )
    roles = {r.value for r in plan.required_roles}
    assert "solution" in roles
    assert "constraint" in roles
