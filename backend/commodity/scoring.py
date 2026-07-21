"""Real-time scoring of the commodity-demand model on SAS Viya.

The registered model `commodity_demand_prediction` (trained on
Commodity_Demand_ABT_v3, target `demand_rate`) is published to MAS on the
same Viya environment the SAS Viya Copilot talks to. This module scores the
bundled forecast calendar against it through the Micro Analytic Score REST
API — the same calls `score_data` in the vendored Viya MCP toolset makes,
batched here so one tool call can score all 576 forecast records without
blowing up the agent's context.

The scored baseline is cached in-process; drivers/scenarios are deterministic
math on top of it (see engine.py), exactly like the Strategic Reserve Monitor
dashboard — no re-scoring when a lever moves.

If the Viya environment is not configured or unreachable, the bundled
offline sample rates are used instead and every result is labeled
`source: "offline_sample"` so the agent can say so honestly.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from sasviya import config as viya_config
from sasviya.tools import get_token
from sasviya.viya_utils import _get_json, _get_paged_items, _make_client, _post_json
from toolset import ToolError

from . import data as D

logger = viya_config.logger

# The MAS module name for the registered model. MAS lowercases module names;
# override with COMMODITY_MODULE_ID if the deployment used a different name.
MODULE_ID = os.getenv("COMMODITY_MODULE_ID", "commodity_demand_prediction").strip()
SCORE_CONCURRENCY = int(os.getenv("COMMODITY_SCORE_CONCURRENCY", "8"))

# Output columns that carry the predicted demand rate, in preference order.
_PREDICTION_KEYS = ("p_demand_rate", "em_prediction", "prediction",
                    "i_demand_rate", "p_demand_rate_")

_cache: dict = {"baseline": None}
_lock = asyncio.Lock()


class ModuleInfo:
    def __init__(self, module_id: str, step_id: str, input_names: list[str]):
        self.module_id = module_id
        self.step_id = step_id
        self.input_names = input_names   # as declared by MAS (original case)


async def _resolve_module(client) -> ModuleInfo:
    """Find the MAS module and its score step's input signature."""
    module_id = None
    for candidate in (MODULE_ID, MODULE_ID.lower()):
        try:
            mod = await _get_json(f"/microanalyticScore/modules/{candidate}", client)
            module_id = mod.get("id") or candidate
            break
        except Exception:
            continue
    if module_id is None:
        # fall back to searching the module list by name
        items, _ = await _get_paged_items("/microanalyticScore/modules", client,
                                          limit=200)
        want = MODULE_ID.lower()
        for m in items:
            name = str(m.get("name", "")).lower()
            if name == want or want in name or "commodity" in name:
                module_id = m.get("id")
                break
        if module_id is None:
            raise ToolError(
                f"No MAS module matching '{MODULE_ID}' found on "
                f"{viya_config.VIYA_ENDPOINT}. Publish the registered model "
                f"'commodity_demand_prediction' to MAS, or set "
                f"COMMODITY_MODULE_ID to the published module's id "
                f"(list_models_and_decisions shows them).")

    steps, _ = await _get_paged_items(
        f"/microanalyticScore/modules/{module_id}/steps", client, limit=50)
    step = None
    for s in steps:
        if str(s.get("id", "")).lower() in ("score", "execute"):
            step = s
            break
    if step is None and steps:
        step = steps[0]
    if step is None:
        raise ToolError(f"MAS module '{module_id}' exposes no steps to score with.")
    input_names = [i.get("name") for i in (step.get("inputs") or []) if i.get("name")]
    return ModuleInfo(module_id, step.get("id"), input_names)


def _build_inputs(module: ModuleInfo, row: dict) -> dict:
    """Match the module's declared inputs to the forecast row, case-insensitively."""
    if not module.input_names:
        # signature unknown — send every model feature the ABT carries
        keep = ("commodity_code", "governorate", "ramadan_share", "eid_fitr_flag",
                "eid_adha_flag", "school_in_session", "month_num", "time_index",
                "registered_population", "quota_per_person", "full_quota_units")
        return {k: row[k] for k in keep if k in row}
    lower_row = {k.lower(): v for k, v in row.items()}
    inputs = {}
    for name in module.input_names:
        if name.lower() in lower_row:
            inputs[name] = lower_row[name.lower()]
    return inputs


def _extract_rate(outputs: list[dict]) -> Optional[float]:
    by_name = {str(o.get("name", "")).lower(): o.get("value") for o in outputs}
    for key in _PREDICTION_KEYS:
        v = by_name.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    for name, v in by_name.items():
        if isinstance(v, (int, float)) and (name.startswith("p_") or name.startswith("em_")):
            return float(v)
    for v in by_name.values():
        if isinstance(v, (int, float)):
            return float(v)
    return None


async def score_record(row: dict) -> dict:
    """Score ONE record live against the MAS module; returns the raw exchange."""
    token = await get_token()
    async with _make_client(token) as client:
        module = await _resolve_module(client)
        inputs = _build_inputs(module, row)
        body = {"inputs": [{"name": k, "value": v} for k, v in inputs.items()]}
        resp = await _post_json(
            f"/microanalyticScore/modules/{module.module_id}/steps/{module.step_id}",
            client, body=body)
        outputs = resp.get("outputs", [])
        return {"module_id": module.module_id, "step_id": module.step_id,
                "inputs_sent": inputs, "outputs": outputs,
                "demand_rate": _extract_rate(outputs)}


async def _score_all_rows() -> dict:
    """Score every forecast-calendar row against the MAS module."""
    token = await get_token()
    rows = D.forecast_rows()
    t0 = time.monotonic()
    async with _make_client(token) as client:
        module = await _resolve_module(client)
        sem = asyncio.Semaphore(SCORE_CONCURRENCY)
        failures: list[str] = []

        async def one(row):
            body = {"inputs": [{"name": k, "value": v}
                               for k, v in _build_inputs(module, row).items()]}
            async with sem:
                for attempt in (1, 2):
                    try:
                        resp = await _post_json(
                            f"/microanalyticScore/modules/{module.module_id}"
                            f"/steps/{module.step_id}", client, body=body)
                        rate = _extract_rate(resp.get("outputs", []))
                        if rate is None:
                            raise ToolError("no numeric prediction in outputs")
                        return max(0.0, rate)
                    except Exception as e:
                        if attempt == 2:
                            failures.append(f"{row['commodity_code']}|"
                                            f"{row['governorate']}|{row['month']}: {e}")
                            return None
                        await asyncio.sleep(0.5)

        rates = await asyncio.gather(*(one(r) for r in rows))

    if failures:
        raise ToolError(
            f"{len(failures)} of {len(rows)} scoring calls failed against MAS "
            f"module '{module.module_id}' (first: {failures[0][:300]}).")

    month_idx = {m: i for i, m in enumerate(D.months())}
    scored = []
    for row, rate in zip(rows, rates):
        r = dict(row)
        r["demand_rate"] = float(rate)
        r["demand_units"] = float(rate) * row["full_quota_units"]
        r["month_idx"] = month_idx[row["month"]]
        scored.append(r)
    return {"source": "live_model", "module_id": module.module_id,
            "rows": scored, "calls": len(rows),
            "ms": int((time.monotonic() - t0) * 1000)}


def _js_round1(x: float) -> float:
    """JavaScript's (x).toFixed(1) for positive x — round half AWAY from zero.

    The dashboard derives full_quota_units as +(quota*pop).toFixed(1), while
    the forecast Excel was written with Python's round-half-to-even; 30 of
    576 rows differ by exactly 0.1. The offline fallback must reproduce the
    dashboard's offline preview digit-for-digit, so it re-derives the quota
    the dashboard's way. (Live scoring still sends the official Excel
    full_quota_units to the model.)"""
    import math
    return math.floor(x * 10 + 0.5) / 10


def _offline_baseline() -> dict:
    month_idx = {m: i for i, m in enumerate(D.months())}
    scored = []
    for row in D.forecast_rows():
        mi = month_idx[row["month"]]
        rate = D.fallback_rate(row["commodity_code"], row["governorate"], mi)
        r = dict(row)
        r["full_quota_units"] = _js_round1(
            row["quota_per_person"] * row["registered_population"])
        r["demand_rate"] = rate
        r["demand_units"] = rate * r["full_quota_units"]
        r["month_idx"] = mi
        scored.append(r)
    return {"source": "offline_sample", "module_id": None,
            "rows": scored, "calls": 0, "ms": 0}


async def warm_baseline() -> None:
    """Pre-score the baseline at startup so the first question is instant.

    Only a LIVE result is kept: if the warm-up ends up on the offline
    fallback (Viya slow to come up, transient auth issue), the cache is
    cleared again so the first real question retries against the model
    instead of being stuck on the sample."""
    if not viya_config.VIYA_ENDPOINT:
        return
    try:
        result = await baseline()
    except Exception as e:              # never let warm-up take the app down
        logger.warning("baseline warm-up failed: %s", e)
        return
    if result.get("source") == "live_model":
        logger.info("baseline warmed: %s calls in %sms",
                    result.get("calls"), result.get("ms"))
    else:
        async with _lock:
            _cache["baseline"] = None
        logger.warning("baseline warm-up fell back to offline sample; "
                       "cache cleared so the next query retries live")


async def baseline(refresh: bool = False) -> dict:
    """The scored baseline forecast, cached after the first live scoring run."""
    async with _lock:
        if _cache["baseline"] is not None and not refresh:
            return _cache["baseline"]
        if not viya_config.VIYA_ENDPOINT:
            result = _offline_baseline()
            result["note"] = ("SAS Viya is not configured (VIYA_ENDPOINT empty) — "
                              "these are bundled offline sample rates, not live "
                              "model output.")
        else:
            try:
                result = await _score_all_rows()
            except Exception as e:
                logger.warning("live scoring failed, using offline sample: %s", e)
                result = _offline_baseline()
                result["note"] = (
                    f"Live scoring against SAS Viya failed "
                    f"({type(e).__name__}: {str(e)[:300]}) — these are bundled "
                    f"offline sample rates, not live model output.")
        _cache["baseline"] = result
        return result
