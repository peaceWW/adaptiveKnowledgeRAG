from __future__ import annotations

ROLE_CATALOG: list[dict] = [
    {"key": "definition", "label": "definition", "category": "CORE CONCEPTS", "color": "#facc15", "keywords": ["定义", "是指", "definition", "refers to"], "description": "术语与概念定义"},
    {"key": "explanation", "label": "explanation", "category": "CORE CONCEPTS", "color": "#fdba74", "keywords": ["说明", "explanation", "note"], "description": "补充解释"},
    {"key": "principle", "label": "principle", "category": "CORE CONCEPTS", "color": "#93c5fd", "keywords": ["原理", "principle", "机制"], "description": "机理与原理"},
    {"key": "classification", "label": "classification", "category": "CORE CONCEPTS", "color": "#c4b5fd", "keywords": ["分类", "classification"], "description": "分类体系"},
    {"key": "related_concept", "label": "related concept", "category": "CORE CONCEPTS", "color": "#a5b4fc", "keywords": ["相关", "related"], "description": "相关概念"},
    {"key": "background", "label": "background", "category": "CORE CONCEPTS", "color": "#d6d3d1", "keywords": ["背景", "background"], "description": "背景信息"},
    {"key": "summary", "label": "summary", "category": "CORE CONCEPTS", "color": "#e7e5e4", "keywords": ["摘要", "summary", "概述"], "description": "摘要概述"},
    {"key": "constraint", "label": "constraint", "category": "RULES & CONSTRAINTS", "color": "#fb923c", "keywords": ["约束", "必须", "禁止", "shall", "must"], "description": "硬性约束"},
    {"key": "parameter", "label": "parameter", "category": "RULES & CONSTRAINTS", "color": "#f97316", "keywords": ["参数", "parameter"], "description": "参数指标"},
    {"key": "rule", "label": "rule", "category": "RULES & CONSTRAINTS", "color": "#f87171", "keywords": ["规则", "rule"], "description": "设计/业务规则"},
    {"key": "exception", "label": "exception", "category": "RULES & CONSTRAINTS", "color": "#c084fc", "keywords": ["例外", "exception", "不适用于"], "description": "例外条件"},
    {"key": "formula", "label": "formula", "category": "RULES & CONSTRAINTS", "color": "#f472b6", "keywords": ["公式", "formula", "mtbf"], "description": "公式计算"},
    {"key": "requirement", "label": "requirement", "category": "RULES & CONSTRAINTS", "color": "#fb7185", "keywords": ["需求", "requirement", "应当"], "description": "规格需求"},
    {"key": "obligation", "label": "obligation", "category": "RULES & CONSTRAINTS", "color": "#ef4444", "keywords": ["应当", "义务", "obligation"], "description": "法定义务"},
    {"key": "prohibition", "label": "prohibition", "category": "RULES & CONSTRAINTS", "color": "#b91c1c", "keywords": ["禁止", "不得", "prohibition"], "description": "禁止条款"},
    {"key": "clause", "label": "clause", "category": "RULES & CONSTRAINTS", "color": "#e11d48", "keywords": ["条款", "clause"], "description": "合同/法规条款"},
    {"key": "example", "label": "example", "category": "APPLICATION & CONTEXT", "color": "#4ade80", "keywords": ["例如", "示例", "example"], "description": "示例说明"},
    {"key": "reference", "label": "reference", "category": "APPLICATION & CONTEXT", "color": "#86efac", "keywords": ["参考", "reference", "参见"], "description": "引用参考"},
    {"key": "solution", "label": "solution", "category": "APPLICATION & CONTEXT", "color": "#34d399", "keywords": ["解决", "推荐使用", "solution"], "description": "解决方案"},
    {"key": "procedure", "label": "procedure", "category": "APPLICATION & CONTEXT", "color": "#2dd4bf", "keywords": ["流程", "procedure", "步骤如下"], "description": "操作流程"},
    {"key": "step", "label": "step", "category": "APPLICATION & CONTEXT", "color": "#5eead4", "keywords": ["步骤", "step", "首先"], "description": "步骤拆解"},
    {"key": "actor", "label": "actor", "category": "APPLICATION & CONTEXT", "color": "#67e8f9", "keywords": ["角色", "负责人", "actor"], "description": "责任角色"},
    {"key": "best_practice", "label": "best practice", "category": "APPLICATION & CONTEXT", "color": "#22d3ee", "keywords": ["最佳实践", "best practice"], "description": "最佳实践"},
    {"key": "comparison", "label": "comparison", "category": "APPLICATION & CONTEXT", "color": "#38bdf8", "keywords": ["对比", "vs", "comparison"], "description": "方案对比"},
    {"key": "root_cause", "label": "root cause", "category": "TECHNICAL DETAILS", "color": "#818cf8", "keywords": ["原因", "root cause", "caused by"], "description": "根因"},
    {"key": "symptom", "label": "symptom", "category": "TECHNICAL DETAILS", "color": "#a78bfa", "keywords": ["现象", "symptom", "failure"], "description": "故障现象"},
    {"key": "prevention", "label": "prevention", "category": "TECHNICAL DETAILS", "color": "#8b5cf6", "keywords": ["预防", "prevention"], "description": "预防措施"},
    {"key": "impact", "label": "impact", "category": "TECHNICAL DETAILS", "color": "#7c3aed", "keywords": ["影响", "impact"], "description": "影响范围"},
    {"key": "environment", "label": "environment", "category": "TECHNICAL DETAILS", "color": "#6d28d9", "keywords": ["环境", "environment"], "description": "运行环境"},
    {"key": "api_input", "label": "api input", "category": "TECHNICAL DETAILS", "color": "#0ea5e9", "keywords": ["input", "request", "入参"], "description": "接口入参"},
    {"key": "api_output", "label": "api output", "category": "TECHNICAL DETAILS", "color": "#0284c7", "keywords": ["output", "response", "返回"], "description": "接口出参"},
    {"key": "error_code", "label": "error code", "category": "TECHNICAL DETAILS", "color": "#0369a1", "keywords": ["error", "错误码", "status code"], "description": "错误码"},
    {"key": "metric", "label": "metric", "category": "TECHNICAL DETAILS", "color": "#075985", "keywords": ["指标", "metric", "kpi"], "description": "量化指标"},
    {"key": "limitation", "label": "limitation", "category": "TECHNICAL DETAILS", "color": "#64748b", "keywords": ["限制", "limitation", "不支持"], "description": "能力边界"},
    {"key": "interface", "label": "interface", "category": "TECHNICAL DETAILS", "color": "#334155", "keywords": ["接口", "interface"], "description": "接口说明"},
    {"key": "sla", "label": "sla", "category": "PROCESS & LEGAL", "color": "#f59e0b", "keywords": ["sla", "时效", "截止"], "description": "服务时效"},
    {"key": "checklist", "label": "checklist", "category": "PROCESS & LEGAL", "color": "#d97706", "keywords": ["清单", "checklist", "检查项"], "description": "检查清单"},
    {"key": "warning", "label": "warning", "category": "PROCESS & LEGAL", "color": "#ea580c", "keywords": ["警告", "注意", "warning"], "description": "风险警告"},
    {"key": "assumption", "label": "assumption", "category": "PROCESS & LEGAL", "color": "#ca8a04", "keywords": ["假设", "assumption", "前提"], "description": "前提假设"},
    {"key": "scope", "label": "scope", "category": "PROCESS & LEGAL", "color": "#a16207", "keywords": ["范围", "scope", "适用"], "description": "适用范围"},
    {"key": "timeline", "label": "timeline", "category": "PROCESS & LEGAL", "color": "#78716c", "keywords": ["时间线", "timeline", "发生于"], "description": "时间线"},
    {"key": "decision", "label": "decision", "category": "PROCESS & LEGAL", "color": "#57534e", "keywords": ["决策", "决定", "decision"], "description": "决策记录"},
    {"key": "consequence", "label": "consequence", "category": "PROCESS & LEGAL", "color": "#44403c", "keywords": ["后果", "导致", "consequence"], "description": "后果影响"},
]


ROLE_LABELS = {
    "definition": "概念定义", "explanation": "解释说明", "principle": "技术原理", "classification": "分类体系",
    "related_concept": "相关概念", "background": "背景知识", "summary": "摘要总结", "constraint": "约束条件",
    "parameter": "参数指标", "rule": "设计规则", "exception": "例外情况", "formula": "公式", "requirement": "规格需求",
    "obligation": "法定义务", "prohibition": "禁止事项", "clause": "条款", "example": "应用示例", "reference": "参考文献",
    "solution": "解决方案", "procedure": "操作流程", "step": "执行步骤", "actor": "责任角色", "best_practice": "最佳实践",
    "comparison": "方案对比", "root_cause": "根因分析", "symptom": "故障现象", "prevention": "预防措施", "impact": "影响范围",
    "environment": "运行环境", "api_input": "接口入参", "api_output": "接口出参", "error_code": "错误码", "metric": "性能指标",
    "limitation": "能力边界", "interface": "接口说明", "sla": "服务时效", "checklist": "检查清单", "warning": "风险警告",
    "assumption": "前提假设", "scope": "适用范围", "timeline": "时间线", "decision": "决策记录", "consequence": "后果影响",
}
CATEGORY_LABELS = {"CORE CONCEPTS": "基础概念", "RULES & CONSTRAINTS": "规则与约束", "APPLICATION & CONTEXT": "应用与流程",
                   "TECHNICAL DETAILS": "技术细节", "PROCESS & LEGAL": "管理与合规", "CUSTOM": "自定义"}
for _role in ROLE_CATALOG:
    _role["label"] = ROLE_LABELS.get(_role["key"], _role["label"])

PREVIEW_SAMPLE = """CDC（Clock Domain Crossing，跨时钟域）是指数字电路中信号从一个时钟域传递到另一个异步时钟域的过程。
CDC 中产生亚稳态的主要原因是数据在接收时钟沿附近发生变化。
单 bit 信号推荐使用双触发器同步器。多 bit 数据推荐 Handshake 或 Async FIFO。
Synchronizer 必须放置在接收时钟域。禁止在 CDC 路径上直接对多 bit 总线做两级触发器同步。
例如异步 FIFO 使用 Gray Code 编码读写指针。
当两个时钟同源且相位关系已知时，该例外不适用于完全异步时钟。
"""
