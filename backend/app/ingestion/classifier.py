from __future__ import annotations

import json

from app.domain.enums import KnowledgeType
from app.model_gateway.gateway import ModelGateway
from app.observability.pipeline_log import step as pipeline_step
from app.prompts.loader import load_prompt

ALLOWED_TYPES = [
    KnowledgeType.TECHNICAL_CONCEPT,
    KnowledgeType.TECHNICAL_SPECIFICATION,
    KnowledgeType.INCIDENT_CASE,
    KnowledgeType.API_DOCUMENT,
    KnowledgeType.UNKNOWN,
]

DEFAULT_PROMPT = """你是芯片设计工程师，按知识本体分类资料。必须输出 JSON：
{"knowledge_type":"...","document_genre":"generic","confidence":0.0,"reason":"...","scores":{}}
"""


class KnowledgeClassifier:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def classify(self, text: str, filename: str = "", structure: dict | None = None) -> dict:
        sample = text[:6000]
        result = self.gateway.chat_json(
            _classifier_system(),
            json.dumps({"filename": filename, "text": sample}, ensure_ascii=False),
        )
        knowledge_type = result.get("knowledge_type", "")
        type_source = "llm"
        if knowledge_type not in {item.value for item in ALLOWED_TYPES}:
            knowledge_type = _heuristic_type(sample, filename)
            type_source = "heuristic"
        scores = result.get("scores") or _heuristic_scores(knowledge_type)
        if (structure or {}).get("genre") == "academic_paper":
            genre = "academic_paper"
            genre_source = "parse.structure.genre"
        else:
            llm_genre = result.get("document_genre")
            genre = llm_genre or _heuristic_genre(sample, filename, structure)
            genre_source = "llm" if llm_genre else "heuristic"
        classified = {
            "knowledge_type": knowledge_type,
            "document_genre": genre,
            "confidence": float(result.get("confidence") or scores.get(knowledge_type, 0.7)),
            "reason": result.get("reason") or "heuristic classification",
            "scores": scores,
        }
        pipeline_step(
            "ingest",
            "classify",
            inputs={
                "filename": filename,
                "text_preview": sample[:200],
                "structure_genre": (structure or {}).get("genre"),
                "llm_knowledge_type": result.get("knowledge_type"),
                "llm_document_genre": result.get("document_genre"),
            },
            result={**classified, "type_source": type_source, "genre_source": genre_source},
        )
        return classified


def _classifier_system() -> str:
    return load_prompt("knowledge-classifier", DEFAULT_PROMPT)


def _heuristic_type(text: str, filename: str) -> str:
    blob = f"{filename}\n{text}".lower()
    chip = any(
        key in blob
        for key in ("adc", "dac", "ffe", "dfe", "ctle", "rtl", "cdc", "enob", "sndr", "jssc", "serdes", "pll", "sar")
    )
    # 电路论文里的 interface/module 不是软件 API
    if not chip and any(k in blob for k in ["api", "endpoint", "request", "response", "openapi"]):
        return KnowledgeType.API_DOCUMENT.value
    if any(k in blob for k in ["incident", "故障", "root cause", "workaround", "失败", "silicon fail"]):
        return KnowledgeType.INCIDENT_CASE.value
    if any(k in blob for k in ["specification", "规范", "shall", "constraint", "setup time", "cdc"]):
        return KnowledgeType.TECHNICAL_SPECIFICATION.value
    return KnowledgeType.TECHNICAL_CONCEPT.value


def _heuristic_genre(text: str, filename: str, structure: dict | None = None) -> str:
    if (structure or {}).get("genre") == "academic_paper":
        return "academic_paper"
    blob = f"{filename}\n{text}".lower()
    academic_hits = sum(
        1
        for key in ("abstract", "references", "ieee", "jssc", "index terms", "10.1109/")
        if key in blob
    )
    if academic_hits >= 2:
        return "academic_paper"
    return "generic"


def _heuristic_scores(primary: str) -> dict[str, float]:
    scores = {
        KnowledgeType.TECHNICAL_SPECIFICATION.value: 0.12,
        KnowledgeType.TECHNICAL_CONCEPT.value: 0.12,
        KnowledgeType.INCIDENT_CASE.value: 0.06,
        KnowledgeType.API_DOCUMENT.value: 0.05,
    }
    scores[primary] = 0.82
    return scores
