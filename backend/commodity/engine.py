"""Deterministic reserve engine on top of the scored baseline forecast.

This is the same math the Strategic Reserve Monitor dashboard runs in the
browser: the model on SAS Viya is scored once for the baseline demand rates,
then drivers (demand surge, quota change, population change, supply
disruption, policy levers) are applied deterministically — no re-scoring.
Keeping the chatbot's math identical to the dashboard means the two never
disagree in a demo.
"""
from __future__ import annotations

from . import data as D

# Dashboard lever defaults
DEFAULT_MIN_COVER_MONTHS = 3.0
DEFAULT_STARTING_RESERVE_MONTHS = 5.0


def aggregate_baseline(rows: list[dict], code: str) -> dict:
    """Collapse the scored rows for one commodity to monthly totals."""
    n = len(D.months())
    base = [0.0] * n
    full_quota = [0.0] * n
    gov_demand: dict[str, float] = {g: 0.0 for g in D.governorates()}
    for r in rows:
        if r["commodity_code"] != code:
            continue
        mi = r["month_idx"]
        base[mi] += r["demand_units"]
        full_quota[mi] += r["full_quota_units"]
        gov_demand[r["governorate"]] += r["demand_units"]
    return {"base": base, "full_quota": full_quota, "gov_demand": gov_demand}


def scenario(rows: list[dict], code: str,
             shock_pct: float = 0.0, quota_pct: float = 0.0,
             pop_pct: float = 0.0, disruption_pct: float = 0.0,
             min_cover_months: float = DEFAULT_MIN_COVER_MONTHS,
             starting_reserve_months: float = DEFAULT_STARTING_RESERVE_MONTHS,
             price_per_unit: float | None = None) -> dict:
    agg = aggregate_baseline(rows, code)
    sp = D.supply_policy(code)
    band_hi = abs(D.band()["hi"])
    months = D.months()
    n = len(months)

    qp = 1 + quota_pct / 100
    pp = 1 + pop_pct / 100
    sh = 1 + shock_pct / 100

    ref_m = sum(agg["base"]) / n
    struct = [b * qp * pp for b in agg["base"]]
    demand = [s * sh for s in struct]
    half = [band_hi * fq * qp * pp * sh for fq in agg["full_quota"]]
    demand_lo = [max(d - h, 0.0) for d, h in zip(demand, half)]
    demand_hi = [d + h for d, h in zip(demand, half)]
    deliveries = [sp["baseline_monthly_deliveries_units"] * (1 - disruption_pct / 100)] * n

    fwd = []
    for m in range(n):
        window = struct[m:min(m + 3, n)]
        fwd.append(sum(window) / len(window))
    floor = [min_cover_months * f for f in fwd]

    stock0 = starting_reserve_months * ref_m
    s = s_best = s_worst = stock0
    stock, stock_best, stock_worst, cover = [], [], [], []
    for m in range(n):
        s = max(s + deliveries[m] - demand[m], 0.0)
        s_best = max(s_best + deliveries[m] - demand_lo[m], 0.0)
        s_worst = max(s_worst + deliveries[m] - demand_hi[m], 0.0)
        stock.append(s)
        stock_best.append(s_best)
        stock_worst.append(s_worst)
        cover.append(s / fwd[m] if fwd[m] else 0.0)

    breach = next((m for m in range(n) if stock[m] < floor[m]), None)
    breach_early = next((m for m in range(n) if stock_worst[m] < floor[m]), None)

    min_cover = min(cover)
    min_cover_m = cover.index(min_cover)
    min_surplus = min(v - f for v, f in zip(stock, floor))

    # One-time top-up that keeps the (un-clamped) balance above the floor all
    # year — the dashboard's "cost to hold floor".
    raw = stock0
    max_deficit = 0.0
    for m in range(n):
        raw += deliveries[m] - demand[m]
        deficit = floor[m] - raw
        if deficit > max_deficit:
            max_deficit = deficit
    topup_units = max(0.0, max_deficit)

    price = price_per_unit if price_per_unit is not None else D.default_price(code)
    monthly = [{"month": months[m],
                "demand": round(demand[m], 1),
                "demand_lo": round(demand_lo[m], 1),
                "demand_hi": round(demand_hi[m], 1),
                "deliveries": round(deliveries[m], 1),
                "reserve": round(stock[m], 1),
                "cover_months": round(cover[m], 2),
                "policy_floor": round(floor[m], 1)}
               for m in range(n)]

    return {
        "commodity_code": code,
        "commodity_en": sp["commodity_en"],
        "unit": sp["unit"],
        "levers": {"shock_pct": shock_pct, "quota_pct": quota_pct,
                   "pop_pct": pop_pct, "disruption_pct": disruption_pct,
                   "min_cover_months": min_cover_months,
                   "starting_reserve_months": starting_reserve_months},
        "kpis": {
            "reserve_on_hand_units": round(stock0, 1),
            "demand_12mo_units": round(sum(demand), 1),
            "avg_monthly_demand_units": round(sum(demand) / n, 1),
            "cover_today_months": round(stock0 / fwd[0], 2) if fwd[0] else None,
            "min_cover_months": round(min_cover, 2),
            "min_cover_month": months[min_cover_m],
            "min_surplus_above_floor_units": round(min_surplus, 1),
        },
        "breach": {
            "breach_month": None if breach is None else months[breach],
            "worst_case_breach_month": (None if breach_early is None
                                        else months[breach_early]),
            "holds_all_year": breach is None,
        },
        # Same flag rules as the dashboard's KPI cards
        "status": {
            "cover": ("ok" if min_cover >= min_cover_months else
                      "warning" if min_cover >= min_cover_months - 1 else
                      "alarm"),
            "reserve": "ok" if breach is None else "alarm",
            "worst_case_is_earlier": (breach is not None
                                      and breach_early is not None
                                      and breach_early < breach),
        },
        "cost": {
            "price_per_unit_usd": price,
            "price_is_editable_assumption": True,
            "reserve_value_usd": round(stock0 * price),
            "annual_procurement_usd": round(
                sp["baseline_monthly_deliveries_units"] * 12 * price),
            "topup_units_to_hold_floor": round(topup_units, 1),
            "topup_cost_usd": round(topup_units * price),
        },
        "monthly": monthly,
        "gov_demand_baseline_units": {g: round(v, 1)
                                      for g, v in sorted(agg["gov_demand"].items(),
                                                         key=lambda kv: -kv[1])},
    }
