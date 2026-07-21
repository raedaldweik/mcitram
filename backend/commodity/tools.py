"""Tool bindings for the MCIT Kuwait commodity-demand forecasting agent.

Scoped use-case toolset: grounding, the model-scored baseline forecast,
what-if reserve scenarios, and a single-record live scoring call that shows
the raw MAS exchange. The heavy lifting (576 scoring calls, reserve math)
happens inside the tools so the agent's context stays small.
"""
from __future__ import annotations

from typing import Optional

from toolset import ToolSet, ToolError

from . import data as D
from . import engine as E
from . import scoring as S

commodity = ToolSet("commodity_usecase")

_HORIZON = f"{D.months()[0]} to {D.months()[-1]}"


def _source_block(base: dict) -> dict:
    out = {"source": base["source"], "scoring_calls": base["calls"],
           "scoring_ms": base["ms"]}
    if base.get("module_id"):
        out["mas_module_id"] = base["module_id"]
    if base.get("note"):
        out["note"] = base["note"]
    return out


@commodity.add(
    "get_use_case",
    "Return this assistant's use case: Kuwait's ration-card commodity demand "
    "forecasting for MCIT — the commodities and governorates covered, the "
    "forecast horizon, the SAS model behind the forecast, the supply-policy "
    "parameters, and the scenario levers. Call this first in a new "
    "conversation.",
    {"type": "object", "properties": {}},
)
async def get_use_case():
    return {
        "useCaseName": "MCIT Kuwait — Commodity Demand Forecast & Strategic Reserve",
        "description": (
            "Monthly demand forecasting for Kuwait's subsidized ration-card "
            "commodities, and the strategic-reserve outlook built on top of "
            "it (reserve trajectory vs. the policy cover floor, breach month, "
            "procurement cost to hold the floor)."),
        "model": {
            "project": "commodity demand forecasting",
            "registered_model": "commodity_demand_prediction",
            "kind": "PREDICTION model — given one record (commodity, "
                    "governorate, month features) it predicts demand_rate. "
                    "The 'forecast' is not a separate model: it is this "
                    "prediction model applied across the 12 future calendar "
                    "months. Per-month prediction was a deliberate design "
                    "choice over a time-series forecasting setup — simpler, "
                    "explainable, and scoreable record-by-record in real "
                    "time via MAS. The driver calculations on top are "
                    "deterministic (the dashboard's hardcoded engine, "
                    "mirrored 1:1 here) and never re-score the model.",
            "trained_on": "Commodity_Demand_ABT_v3 — target demand_rate; "
                          "bundled with this app for offline querying "
                          "(query_history) and also in CAS on the Viya "
                          "environment",
            "scored_via": "SAS Micro Analytic Score (MAS) REST — the same "
                          "real-time scoring the Viya MCP toolset's score_data "
                          "tool uses",
            "forecast_inputs": "Commodity_Demand_ABT_v3_forecast calendar, "
                               "bundled with this app (576 records = 8 "
                               "commodities × 6 governorates × 12 months). "
                               "Inputs only — it contains no predictions; the "
                               "model supplies demand_rate.",
            "prediction": "demand_rate — the share of the full quota "
                          "entitlement actually collected; demand_units = "
                          "demand_rate × full_quota_units",
        },
        "history": {
            "table": "Commodity_Demand_ABT_v3 (bundled, query with query_history)",
            "coverage": "2019-01-01 to 2026-06-01 (4,320 rows, actuals)",
            "partitions": {"Train": 2880, "Validate": 864, "Test": 576},
        },
        "forecast_horizon": _HORIZON,
        "commodities": D.commodities(),
        "governorates": D.governorates(),
        "seasonality_features": ["ramadan_share", "eid_fitr_flag",
                                 "eid_adha_flag", "school_in_session",
                                 "month_num", "time_index"],
        "supply_policy": [D.supply_policy(c) for c in D.commodity_codes()],
        "uncertainty_band": {**D.band(),
                             "meaning": "80% band, ± on the demand rate"},
        "dashboard_parity": (
            "The reserve engine and all reference data are ported 1:1 from "
            "the Strategic Reserve Monitor dashboard and verified "
            "field-by-field against it (48 scenario configs, 4,608 values, "
            "zero mismatches) — chat answers and the dashboard never "
            "disagree. Offline sample rates are the dashboard's embedded "
            "offline forecast, digit-for-digit."),
        "scenario_levers": {
            "shock_pct": "demand surge above normal collection (-10..40, default 0)",
            "quota_pct": "change to the per-person quota (-40..40, default 0)",
            "pop_pct": "change to the registered population (-10..30, default 0)",
            "disruption_pct": "share of normal deliveries held up (0..100, default 0)",
            "min_cover_months": "policy floor, months of stock that must stay "
                                "on hand (1..5, default 3)",
            "starting_reserve_months": "stock on hand today in months of "
                                       "normal demand (2..6, default 5)",
        },
        "default_prices_usd_per_unit": {c: D.default_price(c)
                                        for c in D.commodity_codes()},
        "price_note": "procurement prices are editable assumptions, not model output",
    }


@commodity.add(
    "get_demand_forecast",
    "The 12-month demand forecast from the SAS model. On first call this "
    "scores the full forecast calendar against the registered model "
    "commodity_demand_prediction on SAS Viya (576 real-time MAS scoring "
    "calls), then caches the baseline — later calls are instant. Returns "
    "demand in units (demand_rate × full_quota_units) aggregated by month, "
    "commodity, or governorate, with the 80% band. Check `source` in the "
    "result: 'live_model' means real SAS scoring; 'offline_sample' means the "
    "environment was unreachable and bundled sample rates were used — always "
    "tell the user which one they are looking at.",
    {"type": "object",
     "properties": {
         "commodity": {"type": "string",
                       "description": "Optional commodity code or name (e.g. 'RICE' or 'rice') to filter to."},
         "governorate": {"type": "string",
                         "description": "Optional governorate to filter to (e.g. 'Hawalli')."},
         "group_by": {"type": "string", "enum": ["month", "commodity", "governorate"],
                      "description": "Aggregation level (default month)."},
         "refresh": {"type": "boolean",
                     "description": "Force re-scoring against the live model (default false)."}},
     },
)
async def get_demand_forecast(commodity: Optional[str] = None,
                              governorate: Optional[str] = None,
                              group_by: str = "month",
                              refresh: bool = False):
    base = await S.baseline(refresh=refresh)
    rows = base["rows"]
    code = D.resolve_commodity(commodity) if commodity else None
    gov = D.resolve_governorate(governorate) if governorate else None
    rows = [r for r in rows
            if (code is None or r["commodity_code"] == code)
            and (gov is None or r["governorate"] == gov)]
    if not rows:
        raise ToolError("No forecast rows match that filter.")

    band_hi = abs(D.band()["hi"])
    if group_by == "commodity":
        keys = D.commodity_codes()
        key_of = lambda r: r["commodity_code"]
    elif group_by == "governorate":
        keys = D.governorates()
        key_of = lambda r: r["governorate"]
    else:
        group_by = "month"
        keys = D.months()
        key_of = lambda r: r["month"]

    agg = {k: {"demand_units": 0.0, "full_quota_units": 0.0, "rates": []}
           for k in keys}
    for r in rows:
        a = agg[key_of(r)]
        a["demand_units"] += r["demand_units"]
        a["full_quota_units"] += r["full_quota_units"]
        a["rates"].append(r["demand_rate"])

    out_rows = []
    for k in keys:
        a = agg[k]
        if not a["rates"]:
            continue
        half = band_hi * a["full_quota_units"]
        out_rows.append({
            group_by: k,
            "demand_units": round(a["demand_units"], 1),
            "demand_lo_units": round(max(a["demand_units"] - half, 0), 1),
            "demand_hi_units": round(a["demand_units"] + half, 1),
            "avg_demand_rate": round(sum(a["rates"]) / len(a["rates"]), 4),
            "full_quota_units": round(a["full_quota_units"], 1),
        })

    unit = (D.supply_policy(code)["unit"] if code else
            "mixed (kg / litre per commodity)")
    return {**_source_block(base),
            "filter": {"commodity": code, "governorate": gov},
            "group_by": group_by, "unit": unit,
            "horizon": _HORIZON,
            "total_demand_units": round(sum(r["demand_units"] for r in out_rows), 1),
            "rows": out_rows}


@commodity.add(
    "reserve_outlook",
    "Run the strategic-reserve scenario for one commodity on top of the "
    "model's baseline forecast — the same deterministic engine as the "
    "Strategic Reserve Monitor dashboard. Returns KPIs (reserve on hand, "
    "12-month demand, cover today, minimum cover), the month-by-month "
    "reserve trajectory vs. the policy floor, the breach month (expected and "
    "worst-case on the 80% band), and the procurement cost to hold the floor. "
    "All levers optional — defaults are the dashboard's defaults (no shock, "
    "3-month floor, 5 months starting reserve). The baseline demand comes "
    "from the SAS model; levers apply on top without re-scoring.",
    {"type": "object",
     "properties": {
         "commodity": {"type": "string",
                       "description": "Commodity code or name, e.g. 'RICE' or 'frozen chicken'."},
         "shock_pct": {"type": "number", "description": "Demand surge % above normal (-10..40, default 0)."},
         "quota_pct": {"type": "number", "description": "Per-person quota change % (-40..40, default 0)."},
         "pop_pct": {"type": "number", "description": "Registered population change % (-10..30, default 0)."},
         "disruption_pct": {"type": "number", "description": "Share of deliveries held up % (0..100, default 0)."},
         "min_cover_months": {"type": "number", "description": "Policy floor in months (default 3)."},
         "starting_reserve_months": {"type": "number", "description": "Stock on hand today in months (default 5)."},
         "price_per_unit": {"type": "number", "description": "Procurement price USD/unit (defaults to the bundled assumption)."},
         "refresh": {"type": "boolean", "description": "Force re-scoring of the baseline first (default false)."}},
     "required": ["commodity"]},
)
async def reserve_outlook(commodity: str, shock_pct: float = 0.0,
                          quota_pct: float = 0.0, pop_pct: float = 0.0,
                          disruption_pct: float = 0.0,
                          min_cover_months: float = E.DEFAULT_MIN_COVER_MONTHS,
                          starting_reserve_months: float = E.DEFAULT_STARTING_RESERVE_MONTHS,
                          price_per_unit: Optional[float] = None,
                          refresh: bool = False):
    code = D.resolve_commodity(commodity)
    base = await S.baseline(refresh=refresh)
    result = E.scenario(base["rows"], code,
                        shock_pct=shock_pct, quota_pct=quota_pct,
                        pop_pct=pop_pct, disruption_pct=disruption_pct,
                        min_cover_months=min_cover_months,
                        starting_reserve_months=starting_reserve_months,
                        price_per_unit=price_per_unit)
    return {**_source_block(base), **result}


@commodity.add(
    "score_scenario_record",
    "Score ONE forecast record live against the registered model "
    "commodity_demand_prediction via SAS MAS real-time scoring, and return "
    "the raw exchange (module id, inputs sent, model outputs). Use this to "
    "show the actual SAS scoring call behind the forecast, or to score a "
    "custom what-if record — pass `overrides` to change any input (e.g. "
    "{\"ramadan_share\": 1.0, \"registered_population\": 300000}). Requires "
    "the live Viya environment; not available offline.",
    {"type": "object",
     "properties": {
         "commodity": {"type": "string", "description": "Commodity code or name."},
         "governorate": {"type": "string", "description": "Governorate name."},
         "month": {"type": "string",
                   "description": "Forecast month YYYY-MM-DD (first of month), within the horizon."},
         "overrides": {"type": "object",
                       "description": "Optional input overrides applied to the calendar record before scoring."}},
     "required": ["commodity", "governorate", "month"]},
)
async def score_scenario_record(commodity: str, governorate: str, month: str,
                                overrides: Optional[dict] = None):
    code = D.resolve_commodity(commodity)
    gov = D.resolve_governorate(governorate)
    month = (month or "").strip()[:10]
    row = next((r for r in D.forecast_rows()
                if r["commodity_code"] == code and r["governorate"] == gov
                and r["month"] == month), None)
    if row is None:
        raise ToolError(
            f"No forecast record for {code} / {gov} / {month}. The horizon is "
            f"{_HORIZON}; use the first of the month (e.g. {D.months()[0]}).")
    record = dict(row)
    if overrides:
        for k, v in overrides.items():
            record[k] = v
    result = await S.score_record(record)
    result["record"] = {k: record[k] for k in
                        ("month", "commodity_code", "governorate")}
    if result.get("demand_rate") is not None:
        result["demand_units"] = round(
            result["demand_rate"] * float(record["full_quota_units"]), 1)
    return result


@commodity.add(
    "query_history",
    "Query the historical training data (Commodity_Demand_ABT_v3, bundled "
    "from the Excel the model was trained on — Jan 2019 to Jun 2026, 4,320 "
    "rows with ACTUAL demand_rate/demand_units and Train/Validate/Test "
    "partition labels). Works fully offline, no SAS connection needed. "
    "Filter by commodity/governorate/date range/Ramadan, then aggregate "
    "with group_by. Each group returns: rows, avg_demand_rate, "
    "effective_rate (Σ demand_units ÷ Σ full_quota_units), "
    "total_demand_units, total_full_quota_units. Set raw=true for "
    "individual rows instead (capped by limit). Great for seasonality "
    "questions ('how did rice behave in past Ramadans?') and comparing "
    "history to the forecast.",
    {"type": "object",
     "properties": {
         "commodity": {"type": "string", "description": "Optional commodity code or name."},
         "governorate": {"type": "string", "description": "Optional governorate."},
         "date_from": {"type": "string", "description": "Optional start month YYYY-MM-DD (inclusive)."},
         "date_to": {"type": "string", "description": "Optional end month YYYY-MM-DD (inclusive)."},
         "ramadan_only": {"type": "boolean", "description": "Keep only months with ramadan_share > 0."},
         "partition": {"type": "string", "enum": ["Train", "Validate", "Test"],
                       "description": "Optional partition filter."},
         "group_by": {"type": "array", "items": {
                          "type": "string",
                          "enum": ["month", "year", "month_num", "commodity",
                                   "governorate", "partition", "ramadan"]},
                      "description": "Aggregation keys (default ['month'] — one row per month)."},
         "raw": {"type": "boolean", "description": "Return raw rows instead of aggregates (default false)."},
         "limit": {"type": "integer", "description": "Max result rows (default 60, raw default 24)."}},
     },
)
async def query_history(commodity: Optional[str] = None,
                        governorate: Optional[str] = None,
                        date_from: Optional[str] = None,
                        date_to: Optional[str] = None,
                        ramadan_only: bool = False,
                        partition: Optional[str] = None,
                        group_by: Optional[list] = None,
                        raw: bool = False, limit: Optional[int] = None):
    code = D.resolve_commodity(commodity) if commodity else None
    gov = D.resolve_governorate(governorate) if governorate else None
    lo = (date_from or "").strip()[:10] or None
    hi = (date_to or "").strip()[:10] or None
    rows = [r for r in D.history_rows()
            if (code is None or r["commodity_code"] == code)
            and (gov is None or r["governorate"] == gov)
            and (lo is None or r["month"] >= lo)
            and (hi is None or r["month"] <= hi)
            and (not ramadan_only or r["ramadan_share"] > 0)
            and (partition is None or r["partition_label"] == partition)]
    if not rows:
        raise ToolError("No history rows match that filter (history covers "
                        f"{D.history_rows()[0]['month']} to "
                        f"{D.history_rows()[-1]['month']}).")
    filt = {"commodity": code, "governorate": gov, "date_from": lo,
            "date_to": hi, "ramadan_only": ramadan_only, "partition": partition}

    if raw:
        cap = max(1, limit or 24)
        return {"source": "bundled_training_abt", "filter": filt,
                "total_matching": len(rows), "returned": min(len(rows), cap),
                "rows": rows[:cap]}

    keys = [k for k in (group_by or ["month"])
            if k in ("month", "year", "month_num", "commodity", "governorate",
                     "partition", "ramadan")] or ["month"]

    def key_of(r):
        parts = []
        for k in keys:
            if k == "month":
                parts.append(r["month"])
            elif k == "year":
                parts.append(r["month"][:4])
            elif k == "month_num":
                parts.append(r["month_num"])
            elif k == "commodity":
                parts.append(r["commodity_code"])
            elif k == "governorate":
                parts.append(r["governorate"])
            elif k == "partition":
                parts.append(r["partition_label"])
            elif k == "ramadan":
                parts.append("ramadan" if r["ramadan_share"] > 0 else "non_ramadan")
        return tuple(parts)

    agg: dict = {}
    for r in rows:
        a = agg.setdefault(key_of(r), {"rows": 0, "rate_sum": 0.0,
                                       "demand": 0.0, "quota": 0.0})
        a["rows"] += 1
        a["rate_sum"] += r["demand_rate"]
        a["demand"] += r["demand_units"]
        a["quota"] += r["full_quota_units"]

    out = []
    for k in sorted(agg.keys(),
                    key=lambda t: tuple(f"{x:04d}" if isinstance(x, int) else str(x)
                                        for x in t)):
        a = agg[k]
        rec = dict(zip(keys, k))
        rec.update({"rows": a["rows"],
                    "avg_demand_rate": round(a["rate_sum"] / a["rows"], 4),
                    "effective_rate": round(a["demand"] / a["quota"], 4) if a["quota"] else None,
                    "total_demand_units": round(a["demand"], 1),
                    "total_full_quota_units": round(a["quota"], 1)})
        out.append(rec)
    cap = max(1, limit or 60)
    return {"source": "bundled_training_abt", "filter": filt,
            "group_by": keys, "total_groups": len(out),
            "returned": min(len(out), cap), "rows": out[:cap]}


@commodity.add(
    "get_forecast_inputs",
    "Inspect the bundled forecast-calendar records that get scored — the "
    "model's input features (seasonality flags, population, quota, "
    "full_quota_units) per commodity × governorate × month. Useful to show "
    "what goes INTO the model. Filter to keep the result small.",
    {"type": "object",
     "properties": {
         "commodity": {"type": "string", "description": "Optional commodity code or name."},
         "governorate": {"type": "string", "description": "Optional governorate."},
         "month": {"type": "string", "description": "Optional month YYYY-MM-DD."},
         "limit": {"type": "integer", "description": "Max rows to return (default 24)."}},
     },
)
async def get_forecast_inputs(commodity: Optional[str] = None,
                              governorate: Optional[str] = None,
                              month: Optional[str] = None, limit: int = 24):
    code = D.resolve_commodity(commodity) if commodity else None
    gov = D.resolve_governorate(governorate) if governorate else None
    m = (month or "").strip()[:10] or None
    rows = [r for r in D.forecast_rows()
            if (code is None or r["commodity_code"] == code)
            and (gov is None or r["governorate"] == gov)
            and (m is None or r["month"] == m)]
    total = len(rows)
    return {"total_matching": total, "returned": min(total, max(1, limit)),
            "rows": rows[:max(1, limit)]}
