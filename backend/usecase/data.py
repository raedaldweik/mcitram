"""Bundled procurement-integrity use case — synthetic data layer.

A ready-made SAS-flavored dataset (government procurement, amounts in
USD) generated deterministically at first use, with realistic red-flag
patterns planted for the demo:

* a bid-rotation / cover-bidding ring (3 suppliers sharing an owner group)
  in Ministry of Education IT tenders,
* systematic ~40% overpricing by one supplier at the Ministry of Health,
* split purchasing under the 200,000 USD direct-award threshold at the
  Ministry of Sports,
* a repeated single-bidder winner at the Ministry of Transport,
* duplicate invoices scattered across suppliers.

The same use case can later be loaded into SAS (upload the tables to CAS and
point the scoped MCP server at them) — the agent's tool contract stays the
same.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

SEED = 20260705
DIRECT_AWARD_THRESHOLD = 200_000  # USD

ENTITIES = [
    "Ministry of Health", "Ministry of Education", "Ministry of Transport",
    "Ministry of Interior", "Ministry of Municipal Affairs",
    "Ministry of Energy", "Ministry of Finance", "Ministry of Sports",
    "National Data & AI Authority", "Public Works Authority",
]
CATEGORIES = [
    "IT Equipment", "Software Licenses", "Construction", "Medical Supplies",
    "Office Supplies", "Consulting Services", "Facility Maintenance",
    "Vehicles", "Security Services", "Training Services",
]
REGIONS = ["Central Region", "Northern Region", "Eastern Region", "Western Region", "Southern Region", "Coastal Region", "Highland Region", "Metro Region"]

# category → (typical unit price USD, tender value log-mean)
_CAT_PROFILE = {
    "IT Equipment": (4200, 13.2), "Software Licenses": (950, 13.0),
    "Construction": (1800, 15.2), "Medical Supplies": (310, 13.6),
    "Office Supplies": (85, 11.8), "Consulting Services": (1450, 13.4),
    "Facility Maintenance": (240, 12.6), "Vehicles": (98000, 14.3),
    "Security Services": (520, 12.9), "Training Services": (1900, 12.2),
}

RING = ["S021", "S045", "S078"]          # bid-rotation ring (shared owner group OG-077)
OVERPRICER = "S103"                       # Ministry of Health overpricing
SPLITTER = "S230"                         # Ministry of Sports split purchasing
SINGLE_BIDDER = "S150"                    # Ministry of Transport single-bid winner

_lock = threading.Lock()
_D: dict[str, pd.DataFrame] = {}


def _gen_supplier_names(rng, n):
    prefixes = ["Apex", "Northstar", "Coastal", "Nexus", "Meridian", "Modern",
                "United", "National", "Advanced", "Horizon", "Falcon", "Oasis",
                "Bluewater", "Eastern", "Peninsula", "Crown", "Summit", "Rosewood"]
    suffixes = ["Tech", "Trading", "Contracting", "Medical", "Supplies",
                "Solutions", "Logistics", "Services", "Industries", "Systems",
                "Group", "Est."]
    names, seen = [], set()
    while len(names) < n:
        nm = f"{prefixes[rng.integers(len(prefixes))]} {suffixes[rng.integers(len(suffixes))]}"
        if nm in seen:
            nm = f"{nm} {len(names) % 97 + 2}"
        seen.add(nm)
        names.append(nm)
    return names


def _build() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    n_sup = 420

    # ── suppliers ────────────────────────────────────────────────────
    sup_ids = [f"S{i + 1:03d}" for i in range(n_sup)]
    suppliers = pd.DataFrame({
        "supplier_id": sup_ids,
        "supplier_name": _gen_supplier_names(rng, n_sup),
        "primary_category": rng.choice(CATEGORIES, n_sup),
        "region": rng.choice(REGIONS, n_sup, p=[.32, .2, .14, .09, .08, .06, .06, .05]),
        "registration_year": rng.integers(2005, 2025, n_sup),
        "employee_count": np.round(np.exp(rng.normal(3.6, 1.1, n_sup))).astype(int) + 3,
        "owner_group": [f"OG-{i + 1:03d}" for i in range(n_sup)],
    })
    idx = {s: i for i, s in enumerate(sup_ids)}
    # shared ownership: the ring, plus one benign pair
    for s in RING:
        suppliers.loc[idx[s], "owner_group"] = "OG-077"
    suppliers.loc[idx["S200"], "owner_group"] = "OG-120"
    suppliers.loc[idx["S201"], "owner_group"] = "OG-120"
    suppliers.loc[idx["S021"], "supplier_name"] = "Apex Advanced Tech"
    suppliers.loc[idx["S045"], "supplier_name"] = "Nexus Digital Systems"
    suppliers.loc[idx["S078"], "supplier_name"] = "Falcon Information Tech"
    suppliers.loc[idx[OVERPRICER], "supplier_name"] = "Peninsula Medical Trading"
    suppliers.loc[idx[SPLITTER], "supplier_name"] = "Summit Sports Supplies"
    suppliers.loc[idx[SINGLE_BIDDER], "supplier_name"] = "Eastern Roads Contracting"
    for s in RING:
        suppliers.loc[idx[s], "primary_category"] = "IT Equipment"
    suppliers.loc[idx[OVERPRICER], "primary_category"] = "Medical Supplies"
    suppliers.loc[idx[SPLITTER], "primary_category"] = "Office Supplies"
    suppliers.loc[idx[SINGLE_BIDDER], "primary_category"] = "Construction"

    # candidate bidders per category (suppliers bid mostly in their category)
    by_cat = {c: suppliers[suppliers.primary_category == c].supplier_id.tolist()
              for c in CATEGORIES}

    start = datetime(2023, 1, 1)
    days_span = (datetime(2026, 6, 30) - start).days

    tenders, bids, invoices = [], [], []
    t_no = 0

    def add_tender(entity, category, method, publish, submission_days, est_value,
                   bidders_with_amounts, status="awarded"):
        nonlocal t_no
        t_no += 1
        tid = f"T{t_no:05d}"
        close = publish + timedelta(days=int(submission_days))
        winner_id, winning_bid, second_bid = None, None, None
        if status == "awarded" and bidders_with_amounts:
            ordered = sorted(bidders_with_amounts, key=lambda x: x[1])
            winner_id, winning_bid = ordered[0]
            second_bid = ordered[1][1] if len(ordered) > 1 else None
        award = close + timedelta(days=int(rng.integers(7, 45))) if status == "awarded" else None
        tenders.append({
            "tender_id": tid, "entity": entity, "category": category,
            "method": method, "publish_date": publish.date().isoformat(),
            "submission_days": int(submission_days),
            "estimated_value": round(float(est_value), 2),
            "num_bidders": len(bidders_with_amounts),
            "winning_supplier_id": winner_id,
            "winning_bid": round(float(winning_bid), 2) if winning_bid else None,
            "second_lowest_bid": round(float(second_bid), 2) if second_bid else None,
            "award_date": award.date().isoformat() if award else None,
            "status": status,
        })
        for sid, amt in bidders_with_amounts:
            bids.append({"tender_id": tid, "supplier_id": sid,
                         "bid_amount": round(float(amt), 2)})
        # invoices for awarded tenders
        if winner_id and award:
            unit_base, _ = _CAT_PROFILE[category]
            n_inv = int(rng.integers(1, 5))
            remaining = winning_bid
            for k in range(n_inv):
                amt = remaining / (n_inv - k) * float(rng.uniform(0.85, 1.15))
                amt = min(amt, remaining) if k < n_inv - 1 else remaining
                remaining -= amt
                unit = unit_base * float(rng.uniform(0.85, 1.2))
                if winner_id == OVERPRICER and entity == "Ministry of Health":
                    unit = unit_base * float(rng.uniform(1.35, 1.48))
                qty = max(1, int(round(amt / unit)))
                inv_date = award + timedelta(days=int(rng.integers(10, 200)))
                invoices.append({
                    "invoice_id": f"INV{len(invoices) + 1:06d}",
                    "tender_id": tid, "supplier_id": winner_id, "entity": entity,
                    "category": category, "amount": round(float(amt), 2),
                    "unit_price": round(float(unit), 2), "quantity": qty,
                    "invoice_date": inv_date.date().isoformat(),
                })
        return tid

    def market_bidders(category, exclude=(), k=None):
        pool = [s for s in by_cat[category] if s not in exclude]
        if len(pool) < 8:
            pool += [s for s in sup_ids if s not in pool and s not in exclude][:8]
        k = k or int(rng.integers(3, 8))
        return list(rng.choice(pool, size=min(k, len(pool)), replace=False))

    # ── pattern 1: bid-rotation ring (MoE × IT Equipment) ────────────
    ring_wins = 36
    for i in range(ring_wins):
        publish = start + timedelta(days=int(i * days_span / ring_wins + rng.integers(0, 10)))
        est = float(np.exp(rng.normal(13.4, 0.35)))
        winner = RING[i % 3]
        win_amt = est * float(rng.uniform(0.97, 1.04))     # barely below estimate
        bidders = [(winner, win_amt)]
        for other in RING:
            if other != winner:
                bidders.append((other, win_amt * float(rng.uniform(1.05, 1.09))))
        if rng.uniform() < 0.4:  # occasional outside bidder priced out
            out = market_bidders("IT Equipment", exclude=RING, k=1)[0]
            bidders.append((out, win_amt * float(rng.uniform(1.10, 1.2))))
        add_tender("Ministry of Education", "IT Equipment", "open", publish,
                   submission_days=int(rng.integers(5, 8)), est_value=est,
                   bidders_with_amounts=bidders)

    # ── pattern 2: overpricer wins MoH medical/IT contracts ──────────
    for i in range(14):
        publish = start + timedelta(days=int(rng.integers(0, days_span - 90)))
        cat = "Medical Supplies" if i % 3 else "IT Equipment"
        est = float(np.exp(rng.normal(13.5, 0.4)))
        method = "limited" if i % 2 else "direct"
        win_amt = est * float(rng.uniform(0.96, 1.05))
        bidders = [(OVERPRICER, win_amt)]
        if method == "limited":
            for extra in market_bidders(cat, exclude=[OVERPRICER], k=int(rng.integers(1, 3))):
                bidders.append((extra, win_amt * float(rng.uniform(1.03, 1.12))))
        add_tender("Ministry of Health", cat, method, publish,
                   submission_days=int(rng.integers(10, 25)), est_value=est,
                   bidders_with_amounts=bidders)

    # ── pattern 3: split purchasing (MoSports, under 200k) ───────────
    n_clusters = 5
    for c in range(n_clusters):
        anchor = start + timedelta(days=int(rng.integers(60, days_span - 30)))
        for j in range(int(rng.integers(3, 5))):
            publish = anchor + timedelta(days=int(rng.integers(0, 10)))
            est = float(rng.uniform(168_000, 199_000))
            add_tender("Ministry of Sports", "Office Supplies", "direct", publish,
                       submission_days=int(rng.integers(3, 8)), est_value=est,
                       bidders_with_amounts=[(SPLITTER, est * float(rng.uniform(0.98, 1.0)))])

    # ── pattern 4: repeated single-bidder winner (MoT) ───────────────
    for i in range(11):
        publish = start + timedelta(days=int(rng.integers(0, days_span - 60)))
        est = float(np.exp(rng.normal(14.6, 0.5)))
        add_tender("Ministry of Transport", "Construction", "limited", publish,
                   submission_days=int(rng.integers(7, 15)), est_value=est,
                   bidders_with_amounts=[(SINGLE_BIDDER, est * float(rng.uniform(0.97, 1.03)))])

    # ── background tenders (clean) ───────────────────────────────────
    n_bg = 1050
    ent_w = np.array([.16, .15, .11, .11, .1, .08, .09, .06, .07, .07])
    for _ in range(n_bg):
        entity = str(rng.choice(ENTITIES, p=ent_w))
        category = str(rng.choice(CATEGORIES))
        publish = start + timedelta(days=int(rng.integers(0, days_span)))
        _, logmean = _CAT_PROFILE[category]
        est = float(np.exp(rng.normal(logmean, 0.6)))
        u = rng.uniform()
        method = "open" if u < 0.66 else ("limited" if u < 0.92 else "direct")
        status = "awarded" if rng.uniform() > 0.06 else str(
            rng.choice(["under evaluation", "cancelled"]))
        if method == "direct":
            est = min(est, float(rng.uniform(40_000, DIRECT_AWARD_THRESHOLD * 1.4)))
            k = 1
        elif method == "limited":
            k = int(rng.integers(2, 5))
        else:
            k = int(rng.integers(3, 8))
        cands = market_bidders(category, k=k)
        base = est * float(rng.uniform(0.82, 0.99))
        amounts = sorted(base * (1 + rng.uniform(0, 0.28, size=len(cands))))
        bidders = list(zip(cands, amounts))
        add_tender(entity, category, method, publish,
                   submission_days=int(np.clip(rng.normal(21, 7), 4, 60)),
                   est_value=est, bidders_with_amounts=bidders, status=status)

    tenders_df = pd.DataFrame(tenders)
    bids_df = pd.DataFrame(bids)
    invoices_df = pd.DataFrame(invoices)

    # ── duplicate invoices (pattern 5) ───────────────────────────────
    dup_pool = invoices_df.sample(n=18, random_state=7)
    dups = []
    for _, row in dup_pool.iterrows():
        d = row.to_dict()
        d["invoice_id"] = f"INV{len(invoices_df) + len(dups) + 1:06d}"
        d["invoice_date"] = (pd.Timestamp(d["invoice_date"])
                             + pd.Timedelta(days=int(rng.integers(1, 4)))).date().isoformat()
        dups.append(d)
    invoices_df = pd.concat([invoices_df, pd.DataFrame(dups)], ignore_index=True)

    # ── alerts derived from the planted patterns ─────────────────────
    alerts = []

    def add_alert(atype, severity, score, entity, sid, tid, detail, created):
        alerts.append({
            "alert_id": f"A{len(alerts) + 1:04d}", "alert_type": atype,
            "severity": severity, "score": round(float(score), 1),
            "entity": entity, "supplier_id": sid, "tender_id": tid,
            "detail": detail, "created_date": created,
            "status": str(rng.choice(["new", "in_review", "escalated", "closed"],
                                     p=[.38, .3, .17, .15])),
        })

    ring_t = tenders_df[(tenders_df.entity == "Ministry of Education")
                        & (tenders_df.category == "IT Equipment")
                        & (tenders_df.winning_supplier_id.isin(RING))]
    for _, t in ring_t.iterrows():
        add_alert("Bid rotation pattern", "high", rng.uniform(78, 96), t.entity,
                  t.winning_supplier_id, t.tender_id,
                  "Winner rotates within a 3-supplier cluster sharing owner group "
                  "OG-077; losing bids sit 5–9% above the winner (cover-bid shape); "
                  "short submission window.", t.award_date or t.publish_date)

    over_inv = invoices_df[(invoices_df.supplier_id == OVERPRICER)
                           & (invoices_df.entity == "Ministry of Health")]
    for _, v in over_inv.sample(n=min(20, len(over_inv)), random_state=3).iterrows():
        add_alert("Price anomaly", "high", rng.uniform(70, 92), v.entity,
                  v.supplier_id, v.tender_id,
                  f"Unit price {v.unit_price:,.0f} USD is ~40% above the category "
                  f"benchmark for {v.category}.", v.invoice_date)

    split_t = tenders_df[(tenders_df.entity == "Ministry of Sports")
                         & (tenders_df.winning_supplier_id == SPLITTER)]
    for _, t in split_t.iterrows():
        add_alert("Split purchasing", "medium", rng.uniform(55, 80), t.entity,
                  t.winning_supplier_id, t.tender_id,
                  f"Direct award of {t.winning_bid:,.0f} USD sits just below the "
                  f"{DIRECT_AWARD_THRESHOLD:,.0f} USD threshold, clustered with "
                  f"similar awards to the same supplier within days.",
                  t.award_date or t.publish_date)

    single_t = tenders_df[(tenders_df.winning_supplier_id == SINGLE_BIDDER)]
    for _, t in single_t.iterrows():
        add_alert("Repeated single-bidder award", "medium", rng.uniform(50, 75),
                  t.entity, t.winning_supplier_id, t.tender_id,
                  "Limited tender awarded with exactly one bid; the same supplier "
                  "repeatedly wins sole-bid tenders at this entity.",
                  t.award_date or t.publish_date)

    for d in dups:
        add_alert("Duplicate invoice", "high", rng.uniform(65, 90), d["entity"],
                  d["supplier_id"], d["tender_id"],
                  f"Invoice amount {d['amount']:,.0f} USD duplicates an earlier "
                  f"invoice from the same supplier within days.", d["invoice_date"])

    # benign noise alerts (false-positive fodder for triage demos)
    noise = tenders_df[(tenders_df.status == "awarded")
                       & (~tenders_df.winning_supplier_id.isin(
                           RING + [OVERPRICER, SPLITTER, SINGLE_BIDDER]))].sample(
        n=40, random_state=11)
    for _, t in noise.iterrows():
        kind = str(rng.choice(["Short submission window", "New supplier win",
                               "Price anomaly", "Repeated single-bidder award"]))
        add_alert(kind, str(rng.choice(["low", "medium"], p=[.6, .4])),
                  rng.uniform(30, 62), t.entity, t.winning_supplier_id, t.tender_id,
                  "Automated scenario flag; contextual review usually clears these "
                  "(seasonal purchase, niche market, or justified urgency).",
                  t.award_date or t.publish_date)

    alerts_df = pd.DataFrame(alerts)

    return {"suppliers": suppliers, "tenders": tenders_df, "bids": bids_df,
            "invoices": invoices_df, "alerts": alerts_df}


def get_data() -> dict[str, pd.DataFrame]:
    with _lock:
        if not _D:
            _D.update(_build())
    return _D


# ---------------------------------------------------------------------------
# Query layer (procurement_query tool)
# ---------------------------------------------------------------------------

_OPS = {
    "==": lambda s, v: s == v, "!=": lambda s, v: s != v,
    ">": lambda s, v: pd.to_numeric(s, errors="coerce") > float(v),
    "<": lambda s, v: pd.to_numeric(s, errors="coerce") < float(v),
    ">=": lambda s, v: pd.to_numeric(s, errors="coerce") >= float(v),
    "<=": lambda s, v: pd.to_numeric(s, errors="coerce") <= float(v),
    "contains": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
    "in": lambda s, v: s.isin(v if isinstance(v, list) else [v]),
    "not_in": lambda s, v: ~s.isin(v if isinstance(v, list) else [v]),
}

_DATE_COL = {"tenders": "publish_date", "invoices": "invoice_date",
             "alerts": "created_date"}


def _frame(dataset: str) -> pd.DataFrame:
    data = get_data()
    if dataset not in data:
        raise ValueError(f"unknown dataset '{dataset}'; one of {', '.join(data)}")
    return data[dataset].copy()


def _apply_filters(df: pd.DataFrame, filters):
    for f in filters or []:
        col, op, val = f.get("column"), f.get("op", "=="), f.get("value")
        if col not in df.columns:
            raise ValueError(f"unknown column '{col}'; available: {', '.join(df.columns)}")
        if op == "between" and isinstance(val, list) and len(val) == 2:
            num = pd.to_numeric(df[col], errors="coerce")
            df = df[(num >= float(val[0])) & (num <= float(val[1]))]
            continue
        if op not in _OPS:
            raise ValueError(f"unknown op '{op}'")
        df = df[_OPS[op](df[col], val)]
    return df


def _records(df: pd.DataFrame, limit: int) -> list[dict]:
    out = df.head(limit)
    return [{k: (None if pd.isna(v) else (round(float(v), 2) if isinstance(v, (float, np.floating)) else
                 (int(v) if isinstance(v, (np.integer,)) else v)))
             for k, v in row.items()} for row in out.to_dict("records")]


def describe_dataset(dataset: str) -> dict:
    df = _frame(dataset)
    desc = {"dataset": dataset, "rows": int(len(df)),
            "columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]}
    cats = {}
    for c in df.columns:
        if df[c].dtype == object and df[c].nunique() <= 25:
            cats[c] = sorted(x for x in df[c].dropna().unique().tolist())
    if cats:
        desc["categorical_values"] = cats
    return desc


def kpis() -> dict:
    d = get_data()
    t, inv, al = d["tenders"], d["invoices"], d["alerts"]
    awarded = t[t.status == "awarded"]
    single = awarded[awarded.num_bidders == 1]
    flagged_tenders = set(al.tender_id.dropna())
    flagged_spend = awarded[awarded.tender_id.isin(flagged_tenders)].winning_bid.sum()
    return {
        "period": f"{t.publish_date.min()} → {t.publish_date.max()}",
        "tenders_total": int(len(t)),
        "tenders_awarded": int(len(awarded)),
        "total_awarded_value_sar": round(float(awarded.winning_bid.sum()), 0),
        "avg_bidders_per_tender": round(float(awarded.num_bidders.mean()), 2),
        "single_bid_share_pct": round(100 * len(single) / max(len(awarded), 1), 1),
        "direct_award_share_pct": round(
            100 * (awarded.method == "direct").mean(), 1),
        "invoices_total": int(len(inv)),
        "invoice_value_sar": round(float(inv.amount.sum()), 0),
        "alerts_total": int(len(al)),
        "alerts_open": int((al.status != "closed").sum()),
        "alerts_by_severity": al.severity.value_counts().to_dict(),
        "alerts_by_type": al.alert_type.value_counts().to_dict(),
        "flagged_spend_sar": round(float(flagged_spend), 0),
        "flagged_spend_share_pct": round(
            100 * float(flagged_spend) / max(float(awarded.winning_bid.sum()), 1), 1),
    }


def filter_rows(dataset: str, filters=None, select_columns=None,
                aggregate=None, limit: int = 20) -> dict:
    df = _apply_filters(_frame(dataset), filters)
    result = {"dataset": dataset, "matched": int(len(df))}
    if aggregate and aggregate.get("column"):
        col, func = aggregate["column"], aggregate.get("func", "mean")
        series = pd.to_numeric(df[col], errors="coerce")
        fn = {"mean": series.mean, "median": series.median, "sum": series.sum,
              "min": series.min, "max": series.max, "std": series.std}.get(func)
        if fn is None:
            raise ValueError("aggregate.func must be mean|median|sum|min|max|std")
        val = fn()
        result["aggregate"] = {"column": col, "func": func,
                               "value": None if pd.isna(val) else round(float(val), 2)}
        return result
    if select_columns:
        keep = [c for c in select_columns if c in df.columns]
        df = df[keep] if keep else df
    result["rows"] = _records(df, limit)
    return result


def groupby_aggregate(dataset: str, group_by: str, metric=None, func: str = "count",
                      filters=None, n: int = 30) -> dict:
    df = _apply_filters(_frame(dataset), filters)
    if group_by not in df.columns:
        raise ValueError(f"unknown group_by column '{group_by}'")
    if func == "count" or not metric:
        agg = df.groupby(group_by).size().sort_values(ascending=False)
        rows = [{group_by: k, "count": int(v)} for k, v in agg.head(n).items()]
    else:
        series = pd.to_numeric(df[metric], errors="coerce")
        df = df.assign(_m=series)
        agg = getattr(df.groupby(group_by)["_m"], func)().sort_values(ascending=False)
        rows = [{group_by: k, f"{func}_{metric}": round(float(v), 2)}
                for k, v in agg.head(n).items() if not pd.isna(v)]
    return {"dataset": dataset, "group_by": group_by, "rows": rows}


def top_n(dataset: str, sort_by: str, n: int = 10, ascending: bool = False,
          filters=None, select_columns=None) -> dict:
    df = _apply_filters(_frame(dataset), filters)
    if sort_by not in df.columns:
        raise ValueError(f"unknown sort_by column '{sort_by}'")
    df = df.sort_values(sort_by, ascending=ascending,
                        key=lambda s: pd.to_numeric(s, errors="coerce")
                        if s.dtype != object else s)
    if select_columns:
        keep = [c for c in select_columns if c in df.columns]
        df = df[keep] if keep else df
    return {"dataset": dataset, "rows": _records(df, n)}


def time_series(dataset: str, freq: str = "M", split_by=None, filters=None,
                metric=None, func: str = "count") -> dict:
    date_col = _DATE_COL.get(dataset)
    if not date_col:
        raise ValueError(f"dataset '{dataset}' has no date column for time series")
    df = _apply_filters(_frame(dataset), filters)
    df["_d"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_d"])
    freq = "W" if str(freq).upper() == "W" else ("D" if str(freq).upper() == "D" else "M")
    df["_p"] = df["_d"].dt.to_period(freq).astype(str)
    if metric and func != "count":
        df["_m"] = pd.to_numeric(df[metric], errors="coerce")
        value_of = lambda g: round(float(getattr(g["_m"], func)()), 2)
    else:
        value_of = lambda g: int(len(g))
    rows = []
    if split_by and split_by in df.columns:
        for (p, s), g in df.groupby(["_p", split_by]):
            rows.append({"period": p, split_by: s, "value": value_of(g)})
    else:
        for p, g in df.groupby("_p"):
            rows.append({"period": p, "value": value_of(g)})
    rows.sort(key=lambda r: r["period"])
    return {"dataset": dataset, "date_column": date_col, "freq": freq, "rows": rows}


def histogram(dataset: str, column: str, bins: int = 10, filters=None) -> dict:
    df = _apply_filters(_frame(dataset), filters)
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return {"dataset": dataset, "column": column, "rows": []}
    counts, edges = np.histogram(series, bins=min(max(bins, 2), 40))
    rows = [{"bin": f"{edges[i]:,.0f}–{edges[i + 1]:,.0f}", "count": int(c)}
            for i, c in enumerate(counts)]
    return {"dataset": dataset, "column": column, "rows": rows,
            "mean": round(float(series.mean()), 2),
            "median": round(float(series.median()), 2)}
