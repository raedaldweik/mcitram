"""The MCITRAM agent line-up and the SAS Copilot's specialist sub-agents.

Each agent is a system prompt + one or more toolsets (optionally a subset of
each). The SAS Viya Copilot additionally carries a specialist roster the
runner exposes through a delegate_to_specialist tool — sub-agents run their
own tool loop and report back, and their steps appear in the same trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sasviya.tools import viya
from sasva.tools import va
from websearch.tools import web, sasdocs
from commodity.tools import commodity
from toolset import ToolSet, charts

from . import prompts


@dataclass
class AgentDef:
    id: str
    name: str
    description: str
    system: str
    # list of (toolset, subset-of-tool-names | None for all)
    toolsets: list = field(default_factory=list)
    specialists: dict = field(default_factory=dict)   # id -> AgentDef
    max_iters: int = 14
    # starter prompts shown as chips on a fresh conversation, per language
    suggestions: dict = field(default_factory=dict)   # {"en": [...], "ar": [...]}

    def tool_specs(self) -> list[dict]:
        specs = []
        for ts, subset in self.toolsets:
            specs.extend(ts.specs(subset))
        return specs

    def find_toolset(self, tool_name: str) -> Optional[ToolSet]:
        for ts, subset in self.toolsets:
            names = subset if subset is not None else ts.tool_names
            if tool_name in names and ts.has(tool_name):
                return ts
        return None


# ── SAS Copilot specialists ─────────────────────────────────────────

_DISCOVERY = ["list_cas_servers", "list_caslibs", "list_castables",
              "get_castable_info", "get_castable_columns", "get_castable_data"]

SPECIALISTS = {
    "data_steward": AgentDef(
        id="data_steward", name="Data Steward",
        description="Inventories and profiles data, assesses quality, explains variable relationships.",
        system=prompts.DATA_STEWARD,
        toolsets=[(viya, _DISCOVERY + ["query_table", "explain_data", "list_files"])],
        max_iters=10),
    "data_engineer": AgentDef(
        id="data_engineer", name="Data Engineer",
        description="Generates synthetic data, uploads and prepares tables with SAS code.",
        system=prompts.DATA_ENGINEER,
        toolsets=[(viya, _DISCOVERY + ["query_table", "execute_sas_code",
                                       "generate_synthetic_data", "upload_data",
                                       "promote_table_to_memory", "upload_file"])],
        max_iters=10),
    "model_builder": AgentDef(
        id="model_builder", name="Model Builder",
        description="Builds and evaluates models with AutoML; sets up real-time scoring.",
        system=prompts.MODEL_BUILDER,
        toolsets=[(viya, ["list_ml_projects", "create_ml_project", "run_ml_project",
                          "get_ml_project_results", "delete_ml_project",
                          "list_registered_models", "list_models_and_decisions",
                          "score_data", "execute_sas_code", "query_table",
                          "get_castable_columns", "list_castables"])],
        max_iters=10),
    "insights_reporter": AgentDef(
        id="insights_reporter", name="Insights & Reporting",
        description="Turns tables into KPIs, charts, and an executive narrative.",
        system=prompts.INSIGHTS_REPORTER,
        toolsets=[(viya, _DISCOVERY + ["query_table", "explain_data"]),
                  (charts, None)],
        max_iters=10),
    "platform_guide": AgentDef(
        id="platform_guide", name="Platform Guide",
        description="Answers how-to questions from the official SAS documentation, with sources.",
        system=prompts.PLATFORM_GUIDE,
        toolsets=[(sasdocs, None)],
        max_iters=8),
    "dashboard_designer": AgentDef(
        id="dashboard_designer", name="Dashboard Designer",
        description="Finds, renders, analyzes, and creates Visual Analytics dashboards; recommends KPIs and layout improvements.",
        system=prompts.DASHBOARD_DESIGNER,
        toolsets=[(va, None),
                  (viya, ["list_castables", "get_castable_columns",
                          "get_castable_data", "query_table"])],
        max_iters=12),
}


# ── The public agents ───────────────────────────────────────────────

AGENTS: dict[str, AgentDef] = {
    "commodity-forecast": AgentDef(
        id="commodity-forecast",
        name="Commodity Demand Forecast Copilot",
        description="MCIT Kuwait's commodity copilot — 12-month demand "
                    "forecasts from the SAS model commodity_demand_prediction "
                    "(scored live on SAS Viya), strategic-reserve outlooks "
                    "vs. the policy floor, what-if scenarios, and procurement "
                    "cost to hold the floor.",
        system=prompts.COMMODITY_AGENT,
        toolsets=[(commodity, None),
                  (viya, ["query_table", "list_castables",
                          "get_castable_columns", "get_castable_data",
                          "list_registered_models",
                          "list_models_and_decisions", "score_data"]),
                  (charts, None)],
        max_iters=14,
        suggestions={
            "en": [
                "What does the model forecast for rice demand over the next 12 months?",
                "Will the frozen chicken reserve hold above the 3-month policy floor all year?",
                "What if demand surges 20% during Ramadan and a third of deliveries are delayed?",
                "Score one record live against the SAS model and show me the raw call.",
            ],
            "ar": [
                "ما توقعات النموذج للطلب على الأرز خلال الاثني عشر شهراً القادمة؟",
                "هل يبقى احتياطي الدجاج المجمد فوق حد الثلاثة أشهر طوال العام؟",
                "ماذا لو ارتفع الطلب 20٪ في رمضان وتأخر ثلث الشحنات؟",
                "احسب سجلاً واحداً مباشرة عبر نموذج SAS وأرني الاستدعاء الفعلي.",
            ],
        }),
    "sas-copilot": AgentDef(
        id="sas-copilot",
        name="SAS Viya Copilot",
        description="Your copilot for the SAS Viya platform — explore data, run SAS, "
                    "build models with AutoML, and score in real time, with a team "
                    "of specialist agents.",
        system=prompts.SAS_COPILOT,
        toolsets=[(viya, None), (va, None), (charts, None)],
        specialists=SPECIALISTS,
        max_iters=16,
        suggestions={
            "en": [
                "What data do we have? Give me a quick tour of the environment.",
                "Profile the Commodity_Demand_ABT_v3 table — what drives demand_rate?",
                "List the registered models and score one record against commodity_demand_prediction.",
                "Query average demand_rate by commodity during Ramadan months.",
            ],
            "ar": [
                "ما البيانات المتوفرة لدينا؟ قدّم لي جولة سريعة في البيئة.",
                "حلّل جدول Commodity_Demand_ABT_v3 — ما الذي يحرك معدل الطلب؟",
                "اعرض النماذج المسجّلة واحسب سجلاً واحداً عبر commodity_demand_prediction.",
                "استعلم عن متوسط معدل الطلب حسب السلعة في أشهر رمضان.",
            ],
        }),
    "global-intel": AgentDef(
        id="global-intel",
        name="Global Intelligence (Web Search)",
        description="Scans news and the web — what other countries are doing, "
                    "emerging technologies, and trends that matter to the organization.",
        system=prompts.WEB_AGENT,
        toolsets=[(web, None), (charts, None)],
        max_iters=12,
        suggestions={
            "en": [
                "What's happening in global rice and poultry markets this month?",
                "How do other countries run strategic food reserves? Summarize with sources.",
                "Any supply-chain disruptions that could affect Gulf food imports?",
                "How are governments using AI for food security? Give examples, with sources.",
            ],
            "ar": [
                "ما الجديد في أسواق الأرز والدواجن العالمية هذا الشهر؟",
                "كيف تدير الدول الأخرى الاحتياطيات الغذائية الاستراتيجية؟ لخّص مع المصادر.",
                "هل هناك اضطرابات في سلاسل الإمداد قد تؤثر على واردات الغذاء الخليجية؟",
                "كيف تستخدم الحكومات الذكاء الاصطناعي للأمن الغذائي؟ أعطني أمثلة مع المصادر.",
            ],
        }),
}


def get_agent(agent_id: str) -> Optional[AgentDef]:
    return AGENTS.get(agent_id)


def list_agents() -> list[dict]:
    return [{"id": a.id, "name": a.name, "description": a.description,
             "suggestions": a.suggestions}
            for a in AGENTS.values()]
