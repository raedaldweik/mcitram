"""Runs the real app with a scripted LLM + selected faked tool outputs,
so the UI can be photographed showing realistic agent conversations."""
import asyncio, os, sys, warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("ANTHROPIC_API_KEY", "not-used")
sys.path.insert(0, "/home/user/SAS_Copilot_RAM/backend")
SP = "/tmp/claude-0/-home-user/f62b4483-940b-5855-b24b-3d5ace82edc6/scratchpad"

from services import runner as R
from services import images


class Block:
    def __init__(self, **kw): self.__dict__.update(kw)


class Usage:
    input_tokens = 2400; output_tokens = 310
    cache_read_input_tokens = 2000; cache_creation_input_tokens = 0


class Msg:
    def __init__(self, content): self.content = content; self.usage = Usage()


def T(text): return Block(type="text", text=text)
def TU(i, name, inp): return Block(type="tool_use", id=i, name=name, input=inp)


# ── the dashboard snapshot served by /api/va/image/… ────────────────
with open(f"{SP}/dash_report.png", "rb") as f:
    IMG_ID = images.put(f.read(), "image/png")

REPORT_IMAGE = {
    "kind": "report_image",
    "imageUrl": f"/api/va/image/{IMG_ID}",
    "reportId": "b3a9-ncgr-procurement",
    "reportName": "Procurement Integrity Dashboard",
    "format": "png",
    "viewerUrl": "https://viya.ncgr.gov.sa/SASVisualAnalytics/"
                 "?reportUri=%2Freports%2Freports%2Fb3a9-ncgr-procurement",
    "note": "Live snapshot rendered from SAS Visual Analytics",
}

# ── faked tool outputs (things that need a live SAS/VI/web env) ─────
FAKE_TOOLS = {
    "render_report": REPORT_IMAGE,
    "get_castable_info": {
        "caslib": "PUBLIC", "table": "SUPPLIERS", "rows": 420, "columns": 12,
        "loaded": True, "last_modified": "2026-07-02T09:14:11Z",
    },
    "get_castable_columns": {
        "caslib": "PUBLIC", "table": "SUPPLIERS",
        "columns": [
            {"name": "SUPPLIER_ID", "type": "char", "missing": 0},
            {"name": "SUPPLIER_NAME", "type": "char", "missing": 0},
            {"name": "CR_NUMBER", "type": "char", "missing": 27},
            {"name": "OWNER_GROUP", "type": "char", "missing": 0},
            {"name": "REGION", "type": "char", "missing": 14},
            {"name": "PRIMARY_CATEGORY", "type": "char", "missing": 0},
            {"name": "REGISTERED_DATE", "type": "date", "missing": 0},
            {"name": "STATUS", "type": "char", "missing": 0},
        ],
    },
    "search_alerts": {
        "total_open": 34,
        "alerts": [
            {"alert_id": "AL-2031", "score": 94, "entity": "Gulf Horizon Contracting",
             "type": "Bid rotation pattern", "related_entities": 3, "age_days": 2,
             "status": "open"},
            {"alert_id": "AL-2018", "score": 88, "entity": "Najd Medical Est.",
             "type": "Invoice anomaly", "related_entities": 1, "age_days": 5,
             "status": "open"},
            {"alert_id": "AL-2027", "score": 81, "entity": "Red Sea Logistics",
             "type": "Network link to debarred vendor", "related_entities": 4,
             "age_days": 1, "status": "open"},
            {"alert_id": "AL-2003", "score": 66, "entity": "Oasis Facilities Co.",
             "type": "Split purchasing", "related_entities": 1, "age_days": 9,
             "status": "open"},
            {"alert_id": "AL-1994", "score": 58, "entity": "Dune Star Trading",
             "type": "Short submission window", "related_entities": 2,
             "age_days": 12, "status": "open"},
        ],
    },
    "search_news": {
        "query": "AI procurement oversight government", "total": 4,
        "articles": [
            {"title": "Korea expands AI red-flag screening to all central tenders",
             "url": "https://www.oecd.org/gov/public-procurement/koneps-ai",
             "source": "OECD Public Governance", "published": "2026-06-18",
             "snippet": "KONEPS now screens every central government tender with "
                        "an AI engine that flags collusion and pricing risk before award."},
            {"title": "Brazil's TCU says ALICE ML audits stopped R$1.2bn in rigged bids",
             "url": "https://apnews.com/article/brazil-tcu-alice-procurement-ai",
             "source": "AP News", "published": "2026-05-30",
             "snippet": "The federal audit court's machine-learning system reviews "
                        "supplier networks and flags rigged tenders before contracts sign."},
            {"title": "EU e-procurement rules add algorithmic risk indicators",
             "url": "https://www.euractiv.com/procurement-ai-risk-2026",
             "source": "Euractiv", "published": "2026-06-02",
             "snippet": "From 2027 member states must publish tender risk indicators, "
                        "following Ukraine's open Prozorro model."},
            {"title": "GovTech: agentic AI moves from pilots to procurement floors",
             "url": "https://www.govtech.com/agentic-ai-procurement-2026",
             "source": "GovTech", "published": "2026-06-25",
             "snippet": "Agencies pair LLM copilots with governed analytics platforms "
                        "to keep audit trails intact."},
        ],
    },
}

# ── scripted conversations, consumed in order ───────────────────────
CHART_TOP5 = {
    "chart_type": "bar", "title": "Supplier risk score — top 5 watchlist",
    "data": [
        {"supplier": "Al-Riyadh Advanced Tech", "score": 67.7},
        {"supplier": "Summit Sports Supplies", "score": 61.2},
        {"supplier": "Peninsula Medical Trading", "score": 60.0},
        {"supplier": "Falcon Information Tech", "score": 56.9},
        {"supplier": "Eastern Supplies 3", "score": 53.8},
    ],
    "x_key": "supplier", "y_keys": ["score"],
}

ANSWER_PROC = """**Five suppliers need attention — three distinct patterns.**

| Supplier | Score | Main red flag |
|---|---|---|
| Al-Riyadh Advanced Tech | 67.7 | 48 cover-bid events with related bidders |
| Summit Sports Supplies | 61.2 | 18 direct awards just under the 200k SAR threshold |
| Peninsula Medical Trading | 60.0 | Prices **34.5% above** category benchmark |

- **Al-Riyadh Advanced Tech** and **Falcon Information Tech** share owner group **OG-077** — this looks like one bidding ring operating in IT tenders.
- Recommended: pause new awards to OG-077 pending review, and audit Summit's direct awards for split purchasing.
"""

ANSWER_STEWARD = ("PUBLIC.SUPPLIERS — 420 rows × 12 columns, refreshed 2 July. "
                  "Issues found: CR_NUMBER missing for 27 suppliers (6.4%), REGION "
                  "missing for 14, and 9 probable duplicate suppliers (same CR "
                  "number, different IDs). Recommend dedup + CR backfill before "
                  "any ownership-network modelling.")

ANSWER_COPILOT = """**PUBLIC.SUPPLIERS is model-ready after two fixes.**

- **420 suppliers**, 12 columns, refreshed 2 July.
- **27 missing commercial-registration numbers** (6.4%) — these break ownership matching.
- **9 probable duplicates** — same CR number registered under different supplier IDs.

Want me to hand this to the **data engineer** to deduplicate and backfill, then rebuild the supplier-risk features?
"""

ANSWER_DASH = """**Here's the live dashboard — three things stand out.**

1. **SAR 1.01B awarded** across 1,130 tenders since 2023, trending up.
2. **122 open alerts** — bid-rotation patterns and price anomalies dominate the queue.
3. **Single-bid share is 11.3%** against your 8% target — worth a KPI on the first row.

Ask me to drill into any object — or to create a fresh dashboard from your NCGR template.
"""

CHART_QUEUE = {
    "chart_type": "bar", "title": "Today's queue — alert priority score",
    "data": [
        {"alert": "AL-2031 · Gulf Horizon", "score": 94},
        {"alert": "AL-2018 · Najd Medical", "score": 88},
        {"alert": "AL-2027 · Red Sea Logistics", "score": 81},
        {"alert": "AL-2003 · Oasis Facilities", "score": 66},
        {"alert": "AL-1994 · Dune Star", "score": 58},
    ],
    "x_key": "alert", "y_keys": ["score"],
}

ANSWER_VI = """**Start with AL-2031 — it's both fresh and severe.**

1. **AL-2031 · Gulf Horizon Contracting (94)** — bid-rotation pattern across 3 related bidders; the live tender closes Thursday.
2. **AL-2018 · Najd Medical Est. (88)** — invoice 40% above the contracted schedule.
3. **AL-2027 · Red Sea Logistics (81)** — new network link to a debarred vendor, one day old.

Of the 34 open alerts, two look like probable false positives — say the word and I'll show the reasoning.
"""

ANSWER_WEB = """**Three models are emerging worldwide.**

- **Korea** — every central tender is screened by the KONEPS AI red-flag engine before award.
- **Brazil** — the audit court's **ALICE** system reads supplier networks; it has blocked ~R$1.2bn in rigged bids.
- **EU / Ukraine** — open risk indicators on every tender, becoming law across the EU from 2027.

**For NCGR:** all three began exactly where you are — risk scoring on tender data — then expanded into network analytics. Sources below.
"""

ANSWER_AR = """**خمسة موردين يحتاجون إلى مراجعة عاجلة.**

- **الرياض المتقدمة للتقنية (67.7)** — ثمانية وأربعون حالة «عطاء تغطية» مع شركات مرتبطة بنفس مجموعة الملّاك.
- **سمّيت للتجهيزات الرياضية (61.2)** — ثماني عشرة ترسية مباشرة قُبيل حدّ المائتي ألف ريال مباشرة.
- **بينينسولا للتجارة الطبية (60.0)** — أسعار أعلى من متوسط السوق بنسبة **34.5%**.

تشير البيانات إلى شبكة عطاءات واحدة محتملة في منافسات تقنية المعلومات (مجموعة الملّاك OG-077). هل أُعِدّ لكم تقريراً تنفيذياً بالعربية؟
"""

# scripts keyed by a substring of the user's question — rerun-safe
SCRIPT_MAP = [
    # F first: Arabic key must win before any generic match
    ("الموردون",
     [[ [TU("tu1", "run_model", {"model": "supplier_risk",
                                 "view": "top_suppliers", "n": 5}),
        TU("tu2", "render_chart",
           dict(CHART_TOP5, title="أعلى الموردين خطورة — قائمة المتابعة"))],
       [T(ANSWER_AR)] ]][0]),
    ("riskiest suppliers",
     [[ [T("Running the supplier-risk model across all registered suppliers…"),
        TU("tu1", "run_model", {"model": "supplier_risk",
                                "view": "top_suppliers", "n": 5}),
        TU("tu2", "render_chart", CHART_TOP5)],
       [T(ANSWER_PROC)] ]][0]),
    ("profile the suppliers",
     [[ [TU("tu1", "delegate_to_specialist",
            {"specialist": "data_steward",
             "task": "Profile PUBLIC.SUPPLIERS and flag data-quality issues"})],
       [TU("tu2", "get_castable_info", {"caslib": "PUBLIC", "table": "SUPPLIERS"}),
        TU("tu3", "get_castable_columns", {"caslib": "PUBLIC", "table": "SUPPLIERS"})],
       [T(ANSWER_STEWARD)],
       [T(ANSWER_COPILOT)] ]][0]),
    ("dashboard",
     [[ [T("Fetching the report from SAS Visual Analytics…"),
        TU("tu1", "render_report",
           {"report_name": "Procurement Integrity Dashboard"})],
       [T(ANSWER_DASH)] ]][0]),
    ("look at first",
     [[ [TU("tu1", "search_alerts", {"status": "open", "sort": "score", "limit": 10})],
       [TU("tu2", "render_chart", CHART_QUEUE)],
       [T(ANSWER_VI)] ]][0]),
    ("other countries",
     [[ [TU("tu1", "search_news",
            {"query": "AI procurement oversight government",
             "time_range": "month"})],
       [T(ANSWER_WEB)] ]][0]),
]


def _find_script(question: str):
    q = (question or "").lower()
    for key, blocks in SCRIPT_MAP:
        if key in q:
            return [Msg(list(b)) for b in blocks]
    return [Msg([T("(no staged script matches this question)")])]


async def fake_call(self, system, tools, messages):
    if not hasattr(self, "_script"):
        self._script = _find_script(getattr(self.run, "content", ""))
    await asyncio.sleep(0.9)          # keep the live-activity states visible
    msg = self._script.pop(0)
    self._record_llm(msg.usage)
    return msg


_orig_exec = R.AgentRunner._execute_tool

async def fake_exec(self, agent, name, args, agent_label=""):
    if name in FAKE_TOOLS:
        await asyncio.sleep(0.3)
        return FAKE_TOOLS[name], False
    return await _orig_exec(self, agent, name, args, agent_label)

R.AgentRunner._call_llm = fake_call
R.AgentRunner._execute_tool = fake_exec

import uvicorn
from main import app
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
