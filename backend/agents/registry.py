"""The MCITRAM agent line-up: one agent, the Commodity Demand Forecast
Copilot for MCIT Kuwait.

An agent is a system prompt + one or more toolsets (optionally a subset of
each). The AgentDef dataclass still supports specialist sub-agent rosters
(exposed by the runner as delegate_to_specialist), unused in this lineup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sasviya.tools import viya
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
                "How did rice demand behave during past Ramadans in the training data?",
                "Prepare an executive report on rice supply risk for the reserve committee.",
                "Score one record live against the SAS model and show me the raw call.",
            ],
            "ar": [
                "ما توقعات النموذج للطلب على الأرز خلال الاثني عشر شهراً القادمة؟",
                "هل يبقى احتياطي الدجاج المجمد فوق حد الثلاثة أشهر طوال العام؟",
                "ماذا لو ارتفع الطلب 20٪ في رمضان وتأخر ثلث الشحنات؟",
                "كيف كان الطلب على الأرز في شهور رمضان السابقة في بيانات التدريب؟",
                "أعدّ تقريراً تنفيذياً عن مخاطر إمدادات الأرز للجنة الاحتياطي.",
                "احسب سجلاً واحداً مباشرة عبر نموذج SAS وأرني الاستدعاء الفعلي.",
            ],
        }),
}


def get_agent(agent_id: str) -> Optional[AgentDef]:
    return AGENTS.get(agent_id)


def list_agents() -> list[dict]:
    return [{"id": a.id, "name": a.name, "description": a.description,
             "suggestions": a.suggestions}
            for a in AGENTS.values()]
