# SAS Agentic AI Copilot

A multi-agent AI assistant for the any organization — SAS-branded demo edition — demonstrating **SAS agentic AI with a
customer-owned LLM**. The same UI as the SAS RAM assistant, but with **no
SAS Retrieval Agent Manager dependency**: the agents run in this app against
Anthropic Claude and talk to SAS through the **SAS Viya MCP toolset**
(vendored into this repo).

> **The story for SAS:** SAS Copilot requires SAS-hosted LLMs. This app
> shows the alternative: RAM (or any agent host) + the SAS Viya MCP + the
> LLM of your choice — here Claude Sonnet 5, swappable for an on-prem model.
> The tool layer is identical to the `sas-mcp-server` MCP server, so
> everything demonstrated here transfers 1:1 to a RAM + MCP deployment.

## The four agents (dropdown in the UI)

| Agent | What it does | Backed by |
|---|---|---|
| **SAS Viya Copilot** | Explore the environment, query data, run SAS code, generate data, build models with AutoML, real-time scoring — orchestrating five specialist sub-agents (data steward, data engineer, model builder, insights & reporting, platform guide) | SAS Viya environment via the vendored Viya MCP toolset (`backend/sasviya/`) |
| **Investigation Assistant** | Alert triage for SAS Visual Investigator: work the queue, explain why alerts fired, gather entity networks, flag false positives, recommend actions | VI environment via `backend/sasvi/` (svi-alert + svi-datahub REST) |
| **Procurement Integrity Analyst** | A per-use-case agent: tenders, bids, suppliers, invoices & red-flag alerts for government entities, with ready models (supplier risk, bid-rigging screen, price anomaly) | Bundled synthetic dataset + models (`backend/usecase/`) — runs with zero external dependencies |
| **Global Intelligence** | What other countries/agencies are doing, emerging tech, news monitoring with cited sources | Tavily web search (`backend/websearch/`, vendored from `Web_Search`) |

Everything an agent does is visible: live activity while it works, and a full
tool/LLM trace per answer (the grid icon under each response). Charts the
agents emit (`render_chart`) render as interactive SVG cards. Sub-agent steps
show up in the trace as `specialist › tool`.

**Arabic mode:** the عربي / English button in the header flips the whole UI
to Arabic (RTL layout, Arabic labels, Arabic voice input) and tells the
agents to answer in Modern Standard Arabic — and back again. The choice is
remembered per browser.

## Dashboards (SAS Visual Analytics)

The SAS Viya Copilot (and its `dashboard_designer` specialist) speaks the VA
REST APIs — the OpenAPI specs are vendored in [`docs/va-api/`](docs/va-api/)
with an endpoint inventory in
[`docs/va-api/ENDPOINTS.md`](docs/va-api/ENDPOINTS.md).

**Show & analyze** — *"Show me the procurement dashboard and analyze it"*:
the agent finds the report (`list_va_reports`), renders a live snapshot
server-side (`render_report` → SVG/PNG, displayed as a card in the chat with
zoom + an "Open in SAS Visual Analytics" link), then reads the data behind
the key objects (`get_report_object_data`) and analyzes the actual numbers.
`export_report_pdf` produces a downloadable PDF.

**Create from a template** — `create_report_from_template` copies a styled
template report and re-binds its visuals to a real CAS table via the
report-transforms data-mapping API, saves it as a new report, renders the
result in chat, and recommends enhancements (KPIs to add, better chart
choices).

### Building the template (one-time, in VA)

The data-mapping transform swaps one data source for another, so the
template's objects must be **bound to a placeholder table** (not truly
empty). Recommended recipe:

1. Load a tiny placeholder table, e.g. `Public.DASH_TEMPLATE_DATA` with
   generic columns: `CATEGORY` (char), `SUBCATEGORY` (char), `DATE_VAL`
   (date), `MEASURE1`–`MEASURE4` (numeric). A few dummy rows are enough.
   (You can ask the copilot's data engineer to generate it.)
2. In VA, build your styled dashboard on that table — background design,
   SAS branding, and ~4 objects, e.g. a KPI (`MEASURE1`), bar
   (`CATEGORY` × `MEASURE1`), line (`DATE_VAL` × `MEASURE2`), donut
   (`SUBCATEGORY` × `MEASURE3`).
3. Save it as e.g. **"SAS Dashboard Template"** in `/Public`.

Then in chat: *"Create a procurement dashboard from the template using
Public.PROC_KPIS — map CATEGORY to entity, MEASURE1 to award_value…"* — the
agent checks the columns, proposes the mapping, creates the report, and
shows it. Chart types come from the template; the agent picks the data,
titles, and tells you what to add next.

## Architecture

```
frontend/  React + Vite + Tailwind (copied from Finance_RAM_UI, RAM plumbing removed)
backend/   FastAPI
  ├─ agents/      agent definitions + system prompts (registry.py, prompts.py)
  ├─ services/    the agentic loop (runner.py) + in-memory sessions (store.py)
  ├─ sasviya/     SAS Viya toolset  — vendored from sas-mcp-server (Apache-2.0)
  ├─ sasvi/       SAS Visual Investigator toolset (implements the SAS_VI_MCP roadmap)
  ├─ websearch/   Tavily tools      — vendored from Web_Search
  ├─ usecase/     bundled procurement-integrity data + models
  └─ toolset.py   shared tool registry + render_chart
```

* The LLM is **Claude Sonnet 5** (`MODEL` env var to change) driving a
  standard tool-use loop with streaming and prompt caching.
* The MCP servers are vendored **in-process** — same tool names, arguments,
  and behavior as `sas-mcp-server`, without MCP transport overhead, so the
  whole app ships as **one container**. Swapping back to real MCP servers
  (e.g. under RAM) is a wiring change, not a rewrite.
* Queries run async: `POST /api/query` → poll `GET /api/query/{id}` with the
  live trace at `GET /api/query/{id}/trace` (this avoids gateway timeouts on
  long agent runs — same pattern as the RAM UI).

## Deploying to Railway

1. Push this repo to GitHub and create a Railway service from it — the
   `Dockerfile` + `railway.json` are picked up automatically (two-stage
   build: Vite frontend → FastAPI container, healthcheck on `/api/health`).
2. Set the environment variables (Variables tab). **Required:**

   | Variable | Purpose |
   |---|---|
   | `ANTHROPIC_API_KEY` | The LLM. Only hard requirement to boot. |
   | `VIYA_ENDPOINT` + `VIYA_REFRESH_TOKEN` (or `VIYA_USERNAME`/`VIYA_PASSWORD`) | SAS Viya Copilot |
   | `VI_ENDPOINT` + `VI_USERNAME`/`VI_PASSWORD` + `VI_CLIENT_ID=sas.cli` (or `VI_REFRESH_TOKEN` for SSO identities) | Investigation Assistant |
   | `TAVILY_API_KEY` | Global Intelligence + the copilot's platform-guide specialist |

   Useful optional ones: `SSL_VERIFY=false` / `VI_SSL_VERIFY=false` for
   self-signed certs, `CLIENT_ID`/`VI_CLIENT_ID` (default `sas-mcp`),
   `LLM_EFFORT` (`low`/`medium`/`high`), `MODEL`. Full list with
   explanations: [`backend/.env.example`](backend/.env.example).

3. Agents whose environment isn't configured stay usable in the UI and reply
   with a clear "not configured" explanation — so a partial setup still demos
   cleanly (the Procurement Integrity Analyst always works; it needs nothing).

### Getting a Viya refresh token

Same as the MCP servers: register/use an OAuth client (default `sas-mcp`) and
run `examples/get_refresh_token.py` from the `sas-mcp-server` repo against
each environment (once for Viya, once for VI). Password grant works too for
non-SSO accounts.

## Local development

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
uvicorn main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

## Demo script ideas (SAS)

* **SAS Viya Copilot** — "Brainstorm a driver-risk dataset for a demo,
  generate 5,000 rows, profile it, then build a model with AutoML and score
  one record." Watch the copilot delegate to the data engineer → data steward
  → model builder in the trace.
* **Copilot / platform guide** — "How do I publish a model to MAS in Viya?"
  → answer with citations from documentation.sas.com.
* **Investigation Assistant** — "What should I look at first today?" →
  prioritized alert triage; "Why did this alert fire, and is it a false
  positive?"
* **Procurement Integrity Analyst** — "Run the bid-rigging screen" (finds the
  planted Ministry of Education IT rotation ring), "Who are our riskiest
  suppliers?", "Estimate overpayment from price anomalies" — with charts.
* **Global Intelligence** — "What are other countries doing on AI-driven
  procurement oversight? Anything new this month?"

## Vendored code & licenses

`backend/sasviya/` and parts of `backend/saslogon.py` are adapted from
[sas-mcp-server](https://github.com/raedaldweik/sas-mcp-server) and its
use-case variant (© 2025 SAS Institute Inc., Apache-2.0 — headers retained).
`backend/websearch/` is adapted from the Web_Search news MCP server.
`backend/sasvi/` implements the scope planned in the SAS_VI_MCP roadmap.
