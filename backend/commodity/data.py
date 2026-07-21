"""Bundled data for the MCIT Kuwait commodity-demand use case.

`bundled_data.json` carries:
  • forecast_rows — the Commodity_Demand_ABT_v3_forecast calendar (576 rows:
    8 commodities × 6 governorates × 12 months, Jul 2026 – Jun 2027). These
    are the exact input records scored against the registered SAS model
    `commodity_demand_prediction`. Note: the forecast file holds only model
    INPUTS — no demand_rate — the model supplies the predictions.
  • history_rows — the full training ABT Commodity_Demand_ABT_v3 (4,320
    rows, Jan 2019 – Jun 2026, with actual demand_rate/demand_units and the
    Train/Validate/Test partition labels), bundled from the same Excel the
    model was trained on so the agent can query history with no SAS
    connection. The same table also lives in CAS on the Viya environment.
  • supply_policy — per-commodity baseline deliveries, lead times, starting
    reserve and the policy minimum-cover floor (same figures the Strategic
    Reserve Monitor dashboard uses).
  • band — the 80% uncertainty band on the demand rate (±0.028).
  • fallback_rates — an offline sample of model output (per commodity ×
    governorate × month), used ONLY when the Viya environment is unreachable,
    and always labeled as such.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_HERE = os.path.dirname(os.path.abspath(__file__))


@lru_cache(maxsize=1)
def bundle() -> dict:
    with open(os.path.join(_HERE, "bundled_data.json"), encoding="utf-8") as f:
        return json.load(f)


def forecast_rows() -> list[dict]:
    return bundle()["forecast_rows"]


def history_rows() -> list[dict]:
    return bundle()["history_rows"]


def calendar() -> list[dict]:
    return bundle()["calendar"]


def months() -> list[str]:
    return [c["month"] for c in calendar()]


def commodities() -> list[dict]:
    return bundle()["commodities"]


def commodity_codes() -> list[str]:
    return [c["commodity_code"] for c in commodities()]


def governorates() -> list[str]:
    return bundle()["governorates"]


def supply_policy(code: str) -> dict:
    for sp in bundle()["supply_policy"]:
        if sp["commodity_code"] == code:
            return sp
    raise KeyError(code)


def band() -> dict:
    return bundle()["band"]


def fallback_rate(code: str, governorate: str, month_idx: int) -> float:
    return bundle()["fallback_rates"][f"{code}|{governorate}"][month_idx]


def default_price(code: str) -> float:
    return bundle()["default_prices_usd"].get(code, 1.0)


def resolve_commodity(value: str) -> str:
    """Accept a commodity code or an English name, case-insensitively."""
    v = (value or "").strip().lower()
    for c in commodities():
        if v in (c["commodity_code"].lower(), c["commodity_en"].lower()):
            return c["commodity_code"]
    # allow partial name matches like "rice" or "chicken"
    hits = [c["commodity_code"] for c in commodities()
            if v and v in c["commodity_en"].lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(
        f"Unknown commodity '{value}'. Use one of: "
        + ", ".join(f"{c['commodity_code']} ({c['commodity_en']})"
                    for c in commodities()))


def resolve_governorate(value: str) -> str:
    v = (value or "").strip().lower()
    for g in governorates():
        if v == g.lower():
            return g
    hits = [g for g in governorates() if v and v in g.lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(
        f"Unknown governorate '{value}'. Use one of: "
        + ", ".join(governorates()))
