"""
MCITRAM — MCIT Kuwait Commodity Demand Copilot — FastAPI backend.

Three agents over one chat UI:
  • Commodity Demand Forecast Copilot — the registered SAS model
    commodity_demand_prediction scored live on SAS Viya (MAS), plus the
    strategic-reserve scenario engine
  • SAS Viya Copilot          — SAS Viya MCP toolset + specialist sub-agents
  • Global Intelligence       — Tavily news/web search

Local dev:
    uvicorn main:app --reload --port 8000

Production (Docker):
    uvicorn main:app --host 0.0.0.0 --port $PORT
    Frontend is pre-built at ../frontend/dist and served from "/".

See backend/.env.example for all connection settings.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

from routers import chat as chat_router          # noqa: E402
import sasviya.config as viya_config             # noqa: E402
import websearch.config as web_config            # noqa: E402
import commodity.data as commodity_data          # noqa: E402
import commodity.scoring as commodity_scoring    # noqa: E402
from services import runner                      # noqa: E402

app = FastAPI(
    title="MCITRAM — Commodity Demand Copilot",
    description="MCIT Kuwait multi-agent assistant: commodity demand "
                "forecasting with the SAS model commodity_demand_prediction "
                "scored live on SAS Viya, plus platform copilot and web "
                "intelligence agents.",
    version="0.1.0",
)

# CORS — permissive in dev; in prod the frontend is same-origin so CORS is moot
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router.router)

print(f"✓ LLM: {runner.MODEL} ({'key set' if runner.llm_configured() else 'ANTHROPIC_API_KEY MISSING'})")
print(f"✓ SAS Viya: {viya_config.VIYA_ENDPOINT or '(not configured)'}")
print(f"✓ Commodity model: MAS module '{commodity_scoring.MODULE_ID}' "
      f"({len(commodity_data.forecast_rows())} bundled forecast records"
      f"{'' if viya_config.VIYA_ENDPOINT else ' — offline sample mode'})")
print(f"✓ Tavily web search: {'key set' if web_config.configured() else '(not configured)'}")

# ─── Static frontend ─────────────────────────────────────────────────
FRONTEND_DIST = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist"))

if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{filename:path}")
    def serve_spa(filename: str):
        if filename.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        candidate = os.path.join(FRONTEND_DIST, filename)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    print(f"✓ Serving frontend from {FRONTEND_DIST}")
else:
    @app.get("/")
    def root() -> dict:
        return {
            "service": "SAS Agentic AI Copilot",
            "status": "operational (dev mode — no frontend build found)",
            "hint": "run 'npm run build' in frontend/ for production, or run "
                    "the Vite dev server on :5173",
        }

    print(f"⚠ No frontend build at {FRONTEND_DIST} — API-only mode")
