# MCITRAM — MCIT Kuwait Commodity Demand Copilot

The agentic AI chatbot behind MCIT Kuwait's **commodity demand forecasting**
project and its Strategic Reserve Monitor dashboard. The agents run against
Anthropic Claude and talk to SAS through the **SAS Viya MCP toolset**
(vendored into this repo) — the real forecast comes from the registered SAS
model **`commodity_demand_prediction`**, scored in real time on SAS Viya.

## The use case

Kuwait's ration-card program subsidizes eight commodities — rice (basmati),
frozen chicken, cooking oil, sugar, milk powder, lentils, tomato paste, and
cardamom — across the six governorates (Al Ahmadi, Al Asimah, Al Farwaniya,
Al Jahra, Hawalli, Mubarak Al-Kabeer).

* **Model project:** commodity demand forecasting
* **Registered model:** `commodity_demand_prediction` — predicts
  `demand_rate`, the share of the full quota entitlement actually collected
  (demand in units = `demand_rate × full_quota_units`)
* **Training data:** `Commodity_Demand_ABT_v3` — **bundled into the
  backend** (4,320 rows, Jan 2019 – Jun 2026, actuals + partition labels)
  so history is queryable offline; the same table lives in CAS on the Viya
  environment
* **Forecast inputs:** `Commodity_Demand_ABT_v3_forecast` — the 12-month
  forecast calendar (576 records = 8 commodities × 6 governorates × 12
  months, Jul 2026 – Jun 2027), **bundled into the backend**
  (`backend/commodity/bundled_data.json`) so the agent can score it without
  hunting for inputs
* **Scoring:** SAS Micro Analytic Score (MAS) real-time REST calls — the
  same path as the Viya MCP `score_data` tool, batched in-process so one
  tool call scores all 576 records and caches the baseline

Scenario questions (demand surge, quota change, delivery disruption, policy
floor, starting reserve) run through a deterministic reserve engine on top
of the model baseline — **the exact same math as the Strategic Reserve
Monitor dashboard**, so the chatbot and the dashboard never disagree.

## The agent

One agent: the **Commodity Demand Forecast Copilot** — 12-month demand
forecasts from the SAS model, strategic-reserve outlooks vs. the policy
floor, what-if scenarios, breach months, procurement cost to hold the
floor, historical demand analysis, and live single-record scoring. Backed
by `backend/commodity/` (bundled ABT + forecast calendar + MAS scoring +
reserve engine) plus a subset of the vendored Viya MCP toolset
(`query_table`, model listing, raw `score_data`) for live environment
dives.

### Forecast model vs. SAS model — the distinction

`commodity_demand_prediction` is a **prediction** model: one record in
(commodity, governorate, month features), one `demand_rate` out. There is
no separate forecasting model — the "forecast" is that prediction model
applied across the 576 future calendar records. The forecast Excel
contains **inputs only** (no predictions, no model); the reserve outlook
is deterministic math on top of the model's output.

Everything the agent does is visible: live activity while it works, and a full
tool/LLM trace per answer (the grid icon under each response). Charts the
agents emit (`render_chart`) render as interactive SVG cards.

**Arabic mode:** the عربي / English button in the header flips the whole UI
to Arabic (RTL layout, Arabic labels, Arabic voice input) and tells the
agents to answer in Modern Standard Arabic — and back again.

**Offline resilience:** if the Viya environment is unreachable, the
commodity agent falls back to a bundled offline sample of model output —
every result carries `source: live_model | offline_sample` and the agent is
instructed to say clearly which one the user is looking at.

## The commodity agent's tools (`backend/commodity/`)

| Tool | Purpose |
|---|---|
| `get_use_case` | Grounding: commodities, governorates, horizon, model, supply policy, levers, price assumptions |
| `get_demand_forecast` | Scores the forecast calendar against `commodity_demand_prediction` (cached after the first run); aggregates by month / commodity / governorate with the 80% band |
| `reserve_outlook` | The dashboard's scenario engine: reserve trajectory vs. policy floor, cover, breach month (expected + worst-case), top-up quantity and cost to hold the floor |
| `score_scenario_record` | ONE live MAS call with the raw exchange (module id, inputs, outputs) — shows the actual SAS scoring behind the forecast; supports input overrides |
| `query_history` | The full training ABT (Commodity_Demand_ABT_v3, Jan 2019 – Jun 2026, 4,320 rows with actuals + Train/Validate/Test labels) bundled from the Excel — filter/aggregate with no SAS connection |
| `get_forecast_inputs` | Inspect the bundled input records that get scored |

The agent also carries `query_table`, `list_registered_models`,
`list_models_and_decisions`, `score_data`, and the CAS discovery tools from
the Viya toolset for deeper dives into the ABT and the model repository.

## Architecture

```
frontend/  React + Vite + Tailwind
backend/   FastAPI
  ├─ agents/      agent definitions + system prompts (registry.py, prompts.py)
  ├─ services/    the agentic loop (runner.py) + in-memory sessions (store.py)
  ├─ commodity/   THE use case — bundled ABT + forecast calendar + MAS scoring + reserve engine
  ├─ sasviya/     SAS Viya toolset — vendored from sas-mcp-server (Apache-2.0)
  └─ toolset.py   shared tool registry + render_chart
```

* The LLM is **Claude Sonnet 5** (`MODEL` env var to change) driving a
  standard tool-use loop with streaming and prompt caching.
* The MCP toolsets are vendored **in-process** — same tool names, arguments,
  and behavior as `sas-mcp-server`, without MCP transport overhead, so the
  whole app ships as **one container**. Swapping back to real MCP servers
  (e.g. under RAM) is a wiring change, not a rewrite.
* Queries run async: `POST /api/query` → poll `GET /api/query/{id}` with the
  live trace at `GET /api/query/{id}/trace`.

## Deploying to Railway

1. Push this repo to GitHub and create a Railway service from it — the
   `Dockerfile` + `railway.json` are picked up automatically (two-stage
   build: Vite frontend → FastAPI container, healthcheck on `/api/health`).
2. Set the environment variables (Variables tab). **Required:**

   | Variable | Purpose |
   |---|---|
   | `ANTHROPIC_API_KEY` | The LLM. Only hard requirement to boot. |
   | `VIYA_ENDPOINT` + `VIYA_REFRESH_TOKEN` (or `VIYA_USERNAME`/`VIYA_PASSWORD`) | Live model scoring + the Viya tools |

   Useful optional ones: `COMMODITY_MODULE_ID` (default
   `commodity_demand_prediction` — set it if the MAS module was published
   under a different name; `list_models_and_decisions` in chat shows the
   modules), `SSL_VERIFY=false` for self-signed certs, `LLM_EFFORT`,
   `MODEL`. Full list: [`backend/.env.example`](backend/.env.example).

3. Without Viya configured the agent still demos end-to-end: history and
   forecast inputs are fully bundled, and forecasts fall back to the bundled
   offline sample rates (clearly labeled `offline_sample`).

### Getting a Viya refresh token

Register/use an OAuth client (default `sas-mcp`) and run
`examples/get_refresh_token.py` from the `sas-mcp-server` repo against the
environment. Password grant works too for non-SSO accounts.

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

## Demo script ideas

* **Forecast** — "What does the model forecast for rice demand over the next
  12 months?" → 576 live MAS scoring calls against
  `commodity_demand_prediction`, then a monthly chart with the Ramadan bump.
* **Reserve** — "Will the frozen chicken reserve hold above the 3-month
  policy floor all year?" → verdict, minimum cover and month, trajectory
  chart.
* **What-if** — "Demand surges 20% during Ramadan and a third of deliveries
  are delayed — when do we breach, and what does it cost to hold the floor?"
* **History** — "How did rice demand behave during past Ramadans in the
  training data?" → bundled ABT, no SAS needed.
* **Show the plumbing** — "Score one record live against the SAS model and
  show me the raw call" → module id, inputs, outputs on screen.

## Vendored code & licenses

`backend/sasviya/` and parts of `backend/saslogon.py` are adapted from
[sas-mcp-server](https://github.com/raedaldweik/sas-mcp-server) and its
use-case variant (© 2025 SAS Institute Inc., Apache-2.0 — headers retained).
`backend/websearch/` is adapted from the Web_Search news MCP server.
