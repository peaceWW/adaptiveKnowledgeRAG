from __future__ import annotations

import json
from pathlib import Path

from app.domain.enums import KnowledgeType
from app.model_gateway.gateway import ModelGateway

ALLOWED_TYPES = [
    KnowledgeType.TECHNICAL_CONCEPT,
    KnowledgeType.TECHNICAL_SPECIFICATION,
    KnowledgeType.INCIDENT_CASE,
    KnowledgeType.API_DOCUMENT,
    KnowledgeType.UNKNOWN,
]

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "knowledge-classifier.yaml"


class KnowledgeClassifier:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def classify(self, text: str, filename: str = "") -> dict:
        sample = text[:6000]
        result = self.gateway.chat_json(
            _classifier_system(),
            json.dumps({"filename": filename, "text": sample}, ensure_ascii=False),
        )
        knowledge_type = result.get("knowledge_type", "")
        if knowledge_type not in {item.value for item in ALLOWED_TYPES}:
            knowledge_type = _heuristic_type(sample, filename)
        scores = result.get("scores") or _heuristic_scores(knowledge_type)
        return {
            "knowledge_type": knowledge_type,
            "confidence": float(result.get("confidence") or scores.get(knowledge_type, 0.7)),
            "reason": result.get("reason") or "heuristic classification",
            "scores": scores,
        }


def _classifier_system() -> str:
    return """你是企业知识分类器。任务不是总结文档，而是根据 Knowledge Ontology 分类。
允许的 knowledge_type：
1. technical_concept
2. technical_specification
3. incident_case
4. api_document
如果无法确定：knowledge_type = unknown
不得创造新的类型。必须输出 JSON：
{"knowledge_type":"...","confidence":0.0,"reason":"...","scores":{}}
"""


def _heuristic_type(text: str, filename: str) -> str:
    blob = f"{filename}\n{text}".lower()
    if any(k in blob for k in ["api", "endpoint", "request", "response", "openapi"]):
        return KnowledgeType.API_DOCUMENT.value
    if any(k in blob for k in ["incident", "故障", "root cause", "workaround", "失败"]):
        return KnowledgeType.INCIDENT_CASE.value
    if any(k in blob for k in ["specification", "规范", "shall", "constraint", "setup time", "cdc"]):
        return KnowledgeType.TECHNICAL_SPECIFICATION.value
    return KnowledgeType.TECHNICAL_CONCEPT.value


def _heuristic_scores(primary: str) -> dict[str, float]:
    scores = {
        KnowledgeType.TECHNICAL_SPECIFICATION.value: 0.12,
        KnowledgeType.TECHNICAL_CONCEPT.value: 0.12,
        KnowledgeType.INCIDENT_CASE.value: 0.06,
        KnowledgeType.API_DOCUMENT.value: 0.05,
    }
    scores[primary] = 0.82
    return scores
