"""The SAS demo agent line-up and the SAS Copilot's specialist sub-agents.

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
from sasvi.tools import vi
from websearch.tools import web, sasdocs
from usecase.tools import procurement
from frontline.tools import frontline
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


# ── The four public agents ──────────────────────────────────────────

AGENTS: dict[str, AgentDef] = {
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
                "Generate a 5,000-row synthetic dataset for a supplier-risk demo, then profile it.",
                "Build a model with AutoML on that table and score one record in real time.",
                "Show me the procurement dashboard and analyze it.",
            ],
            "ar": [
                "ما البيانات المتوفرة لدينا؟ قدّم لي جولة سريعة في البيئة.",
                "أنشئ بيانات اصطناعية من 5000 صف لعرض مخاطر الموردين ثم حلّلها.",
                "ابنِ نموذجاً بالتعلّم الآلي على ذلك الجدول واحسب درجة سجل واحد فورياً.",
                "اعرض لوحة معلومات المشتريات وحلّلها.",
            ],
        }),
    "vi-investigator": AgentDef(
        id="vi-investigator",
        name="Investigation Assistant (Visual Investigator)",
        description="Triage copilot for SAS Visual Investigator — work the alert "
                    "queue, explain detections, flag false positives, recommend actions.",
        system=prompts.VI_AGENT,
        toolsets=[(vi, None), (charts, None)],
        max_iters=14,
        suggestions={
            "en": [
                "What should I look at first today?",
                "Triage the highest-priority alert — why did it fire?",
                "Could this alert be a false positive? Walk me through the evidence.",
                "Who is connected to this supplier, and through what?",
            ],
            "ar": [
                "بماذا أبدأ اليوم؟",
                "افرز التنبيه الأعلى أولوية — لماذا انطلق؟",
                "هل يمكن أن يكون هذا التنبيه إنذاراً كاذباً؟ اشرح لي الأدلة.",
                "من يرتبط بهذا المورد وبأي روابط؟",
            ],
        }),
    "procurement-analyst": AgentDef(
        id="procurement-analyst",
        name="Procurement Integrity Analyst",
        description="Use-case agent over government procurement data — tenders, "
                    "suppliers, invoices, red-flag alerts, and ready risk models.",
        system=prompts.PROCUREMENT_AGENT,
        toolsets=[(procurement, None), (charts, None)],
        max_iters=12,
        suggestions={
            "en": [
                "Who are our riskiest suppliers right now?",
                "Run the bid-rigging screen on IT tenders.",
                "How much are we overpaying versus market prices?",
                "Any purchases split to stay under the approval threshold?",
            ],
            "ar": [
                "من هم الموردون الأعلى خطورة حالياً؟",
                "شغّل فحص التواطؤ في عطاءات تقنية المعلومات.",
                "كم ندفع زيادة عن أسعار السوق؟",
                "هل هناك مشتريات مجزّأة للبقاء تحت حد الاعتماد؟",
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
                "What are other countries doing on AI-driven procurement oversight?",
                "What changed in agentic AI this month?",
                "Best practice for supplier risk monitoring — summarize with sources.",
                "How are governments using AI copilots? Give examples, with sources.",
            ],
            "ar": [
                "ماذا تفعل الدول الأخرى في الرقابة على المشتريات بالذكاء الاصطناعي؟",
                "ما الجديد في الذكاء الاصطناعي الوكيل هذا الشهر؟",
                "لخّص أفضل الممارسات في مراقبة مخاطر الموردين مع المصادر.",
                "كيف تستخدم الحكومات المساعدات الذكية؟ أعطني أمثلة مع المصادر.",
            ],
        }),
}


# ── Frontline Assist (social benefits) ──────────────────────────────

_INTEGRATIONS = ["get_beneficiary_profile", "check_icp", "check_mohre",
                 "check_gpssa", "check_card_status", "check_utility"]

FRONTLINE_SPECIALISTS = {
    "knowledge_decision": AgentDef(
        id="knowledge_decision", name="Knowledge & Decision AI Agent",
        description="Analytical backbone — verifies facts across the integrations and runs the deterministic Smart Form engine; evidence-based reports.",
        system=prompts.KNOWLEDGE_DECISION,
        toolsets=[(frontline, _INTEGRATIONS + ["evaluate_complaint"])],
        max_iters=10),
    "document_processing": AgentDef(
        id="document_processing", name="Document Processing AI Agent",
        description="Shared document service — submits uploads to the existing document-intelligence module (IDP) and consumes confidence scores, extracted fields, and rejection reasons.",
        system=prompts.DOCUMENT_PROCESSING,
        toolsets=[(frontline, ["submit_document_to_idp"])],
        max_iters=6),
}

AGENTS["customer-resolution"] = AgentDef(
    id="customer-resolution",
    name="Customer Resolution Agent",
    description="Frontline Assist — resolves Inflation Allowance and SWP "
                "complaints end to end: real-time integration checks, a "
                "deterministic Smart Form decision engine (eight outcomes), "
                "and an AI-document fallback when systems are unavailable.",
    system=prompts.CUSTOMER_RESOLUTION,
    toolsets=[(frontline, None), (charts, None)],
    specialists=FRONTLINE_SPECIALISTS,
    max_iters=14,
    suggestions={
        "en": [
            "I didn't receive my Inflation Allowance this month. My Emirates ID is 784-1990-7654321-3.",
            "My payment card never arrived — ID 784-1978-1122334-5.",
            "Why was my application rejected? ID 784-1995-4455667-8.",
            "The allowance amount looks wrong this month — ID 784-1969-9988776-1.",
        ],
        "ar": [
            "لم أستلم علاوة التضخم هذا الشهر. رقم هويتي 784-1990-7654321-3.",
            "بطاقة الدفع لم تصلني — الهوية 784-1978-1122334-5.",
            "لماذا رُفض طلبي؟ الهوية 784-1995-4455667-8.",
            "مبلغ العلاوة يبدو خاطئاً هذا الشهر — الهوية 784-1969-9988776-1.",
        ],
    })

AGENTS["case-management"] = AgentDef(
    id="case-management",
    name="Case Management Agent",
    description="Supervisor view over the Frontline Assist case queue — SLA "
                "breaches, case timelines with the full inter-agent audit "
                "trail, and queue analytics.",
    system=prompts.CASE_MANAGEMENT,
    toolsets=[(frontline, ["list_cases", "get_case_timeline",
                           "get_beneficiary_profile"]),
              (charts, None)],
    specialists=FRONTLINE_SPECIALISTS,
    max_iters=12,
    suggestions={
        "en": [
            "What's in the case queue today? Anything breaching SLA?",
            "Show me the full timeline for case FA-2026-0142.",
            "Chart open cases by outcome and status.",
        ],
        "ar": [
            "ما الموجود في قائمة الحالات اليوم؟ هل هناك تجاوز لاتفاقية مستوى الخدمة؟",
            "اعرض السجل الكامل للحالة FA-2026-0142.",
            "ارسم الحالات المفتوحة حسب النتيجة والحالة.",
        ],
    })



def get_agent(agent_id: str) -> Optional[AgentDef]:
    return AGENTS.get(agent_id)


def list_agents() -> list[dict]:
    return [{"id": a.id, "name": a.name, "description": a.description,
             "suggestions": a.suggestions}
            for a in AGENTS.values()]
