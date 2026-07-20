"""Analytical models for the procurement-integrity use case.

Three models over the bundled dataset, mirroring what would run as SAS models
in a production deployment (the agent presents them as the use case's ready
models):

* ``supplier_risk``  — composite 0–100 integrity risk score per supplier
* ``bid_rigging``    — collusion screen over (entity × category) markets
* ``price_anomaly``  — unit-price outliers vs category benchmarks
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import DIRECT_AWARD_THRESHOLD, get_data


def _norm(series: pd.Series) -> pd.Series:
    """Scale to 0..1 with a robust cap so one extreme doesn't flatten the rest.
    When the 95th percentile is zero (rare signals), fall back to the max so a
    single event scores proportionally instead of maxing the factor out."""
    s = series.fillna(0).astype(float)
    cap = float(s.quantile(0.95))
    if cap <= 0:
        cap = float(s.max())
    if cap <= 0:
        return s * 0
    return (s / cap).clip(0, 1)


def supplier_risk(view: str = "summary", group_by: str | None = None,
                  n: int = 10) -> dict:
    d = get_data()
    sup, t, inv = d["suppliers"], d["tenders"], d["invoices"]
    awarded = t[(t.status == "awarded") & t.winning_supplier_id.notna()]

    g = awarded.groupby("winning_supplier_id")
    feats = pd.DataFrame({
        "wins": g.size(),
        "award_value": g.winning_bid.sum(),
        "single_bid_wins": g.apply(lambda x: int((x.num_bidders == 1).sum()), include_groups=False),
        "direct_awards": g.apply(lambda x: int((x.method == "direct").sum()), include_groups=False),
        "entity_concentration": g.apply(
            lambda x: float(x.entity.value_counts(normalize=True).max()), include_groups=False),
        "near_threshold": g.apply(
            lambda x: int(((x.method == "direct")
                           & (x.winning_bid > DIRECT_AWARD_THRESHOLD * 0.85)
                           & (x.winning_bid < DIRECT_AWARD_THRESHOLD)).sum()), include_groups=False),
        "short_window_wins": g.apply(lambda x: int((x.submission_days < 8).sum()), include_groups=False),
    })
    feats["single_bid_share"] = feats.single_bid_wins / feats.wins

    # price deviation vs category median unit price
    med = inv.groupby("category").unit_price.median().rename("cat_median")
    iv = inv.merge(med, on="category")
    iv["dev"] = (iv.unit_price - iv.cat_median) / iv.cat_median
    price_dev = iv.groupby("supplier_id").dev.mean().rename("price_dev")
    feats = feats.join(price_dev, how="left")

    # duplicate invoices per supplier
    dup_mask = iv.duplicated(subset=["supplier_id", "amount", "tender_id"], keep=False)
    dup_counts = iv[dup_mask].groupby("supplier_id").size().rename("dup_invoices")
    feats = feats.join(dup_counts, how="left")

    # shared ownership
    og_counts = sup.groupby("owner_group").supplier_id.transform("count")
    shared = sup.assign(shared=(og_counts > 1).astype(int)).set_index("supplier_id")["shared"]
    feats = feats.join(shared, how="left")

    # cover-bid involvement: awarded tenders where a losing bid sits 2–10%
    # above the winner AND the loser shares an owner group with the winner —
    # both sides of that pair get counted (the classic rotation-ring shape).
    d_bids = d["bids"]
    owner_of = sup.set_index("supplier_id")["owner_group"].to_dict()
    joined = d_bids.merge(
        awarded[["tender_id", "winning_supplier_id", "winning_bid"]],
        on="tender_id")
    losers = joined[joined.supplier_id != joined.winning_supplier_id].copy()
    losers["premium"] = (losers.bid_amount - losers.winning_bid) / losers.winning_bid
    losers["same_owner"] = [
        owner_of.get(a) == owner_of.get(b)
        for a, b in zip(losers.supplier_id, losers.winning_supplier_id)]
    cover = losers[(losers.premium.between(0.02, 0.10)) & losers.same_owner]
    cover_counts = pd.concat([cover.supplier_id, cover.winning_supplier_id]) \
        .value_counts().rename("cover_events")
    feats = feats.join(cover_counts, how="left")
    feats = feats.fillna(0)

    # weight one-off direct awards down: a single sole-bid win is routine,
    # a *pattern* of them is the signal
    single_bid_signal = feats.single_bid_share * (feats.wins / 4).clip(upper=1)

    score = (
        20 * _norm(single_bid_signal)
        + 18 * _norm(feats.price_dev.clip(lower=0))
        + 14 * _norm(feats.near_threshold)
        + 20 * _norm(feats.cover_events)
        + 10 * _norm(feats.entity_concentration.where(feats.wins >= 4, 0))
        + 8 * _norm(feats.dup_invoices)
        + 5 * feats.shared * _norm(feats.wins)
        + 5 * _norm(feats.short_window_wins)
    ) * 1.25
    feats["risk_score"] = score.round(1).clip(0, 100)
    feats["tier"] = pd.cut(feats.risk_score, [-1, 40, 55, 72, 101],
                           labels=["low", "elevated", "high", "critical"])

    feats = feats.join(sup.set_index("supplier_id")[
        ["supplier_name", "primary_category", "region", "owner_group"]], how="left")

    if view == "top_suppliers":
        top = feats.sort_values("risk_score", ascending=False).head(n)
        rows = []
        for sid, r in top.iterrows():
            rows.append({
                "supplier_id": sid, "supplier_name": r.supplier_name,
                "risk_score": float(r.risk_score), "tier": str(r.tier),
                "wins": int(r.wins), "award_value_sar": round(float(r.award_value), 0),
                "single_bid_share_pct": round(100 * float(r.single_bid_share), 1),
                "avg_price_premium_pct": round(100 * float(r.price_dev), 1),
                "near_threshold_awards": int(r.near_threshold),
                "cover_bid_events": int(r.cover_events),
                "duplicate_invoices": int(r.dup_invoices),
                "owner_group": r.owner_group, "category": r.primary_category,
                "region": r.region,
            })
        return {"model": "supplier_risk", "view": view, "rows": rows}

    if view == "by_group":
        gb = group_by if group_by in ("region", "primary_category") else "region"
        agg = feats.groupby(gb, observed=True).risk_score.mean().sort_values(ascending=False)
        return {"model": "supplier_risk", "view": view, "group_by": gb,
                "rows": [{gb: k, "avg_risk_score": round(float(v), 1)}
                         for k, v in agg.items()]}

    tiers = feats.tier.value_counts().to_dict()
    return {
        "model": "supplier_risk", "view": "summary",
        "suppliers_scored": int(len(feats)),
        "tier_distribution": {str(k): int(v) for k, v in tiers.items()},
        "avg_score": round(float(feats.risk_score.mean()), 1),
        "scoring_factors": [
            "pattern of single-bid wins (20%)",
            "cover-bid events with related bidders (20%)",
            "price premium vs category benchmark (18%)",
            "direct awards just under the 200k USD threshold (14%)",
            "entity concentration (10%)", "duplicate invoices (8%)",
            "shared ownership with other bidders (5%)",
            "short submission windows (5%)"],
        "note": "Use view='top_suppliers' for the watchlist and view='by_group' "
                "(group_by=region|primary_category) for hotspots.",
    }


def bid_rigging(entity: str | None = None, category: str | None = None,
                n: int = 8) -> dict:
    d = get_data()
    t, sup = d["tenders"], d["suppliers"]
    awarded = t[(t.status == "awarded") & t.winning_supplier_id.notna()
                & (t.method != "direct")]
    if entity:
        awarded = awarded[awarded.entity.str.contains(entity, case=False)]
    if category:
        awarded = awarded[awarded.category.str.contains(category, case=False)]

    owner_of = sup.set_index("supplier_id")["owner_group"].to_dict()
    name_of = sup.set_index("supplier_id")["supplier_name"].to_dict()

    clusters = []
    for (ent, cat), g in awarded.groupby(["entity", "category"]):
        if len(g) < 5:
            continue
        winners = g.winning_supplier_id.value_counts()
        top3_share = winners.head(3).sum() / len(g)
        single_rate = float((g.num_bidders == 1).mean())
        premiums = ((g.second_lowest_bid - g.winning_bid) / g.winning_bid).dropna()
        cover = float(premiums.mean()) if len(premiums) else None
        # tight cover premiums (2–10%) with low variance are the classic shape
        cover_flag = (cover is not None and 0.02 <= cover <= 0.10
                      and (premiums.std() or 1) < 0.04)
        owner_overlap = len({owner_of.get(w) for w in winners.head(3).index}) < min(3, len(winners))
        short_windows = float((g.submission_days < 8).mean())
        suspicion = (
            40 * (top3_share if len(g) >= 8 else top3_share * 0.7)
            + (25 if cover_flag else 0)
            + (20 if owner_overlap else 0)
            + 10 * single_rate
            + 5 * short_windows)
        clusters.append({
            "entity": ent, "category": cat, "tenders": int(len(g)),
            "distinct_winners": int(winners.size),
            "top3_win_share_pct": round(100 * float(top3_share), 1),
            "avg_cover_premium_pct": round(100 * cover, 1) if cover is not None else None,
            "cover_bid_pattern": bool(cover_flag),
            "shared_ownership_among_top_winners": bool(owner_overlap),
            "single_bid_rate_pct": round(100 * single_rate, 1),
            "short_window_rate_pct": round(100 * short_windows, 1),
            "suspicion_score": round(float(suspicion), 1),
            "top_winners": [
                {"supplier_id": w, "supplier_name": name_of.get(w, w),
                 "wins": int(c), "owner_group": owner_of.get(w)}
                for w, c in winners.head(3).items()],
            "example_tenders": g.tender_id.head(5).tolist(),
        })
    clusters.sort(key=lambda c: c["suspicion_score"], reverse=True)
    return {"model": "bid_rigging",
            "markets_screened": len(clusters),
            "flags_explained": ("suspicion combines winner concentration, "
                                "cover-bid shape (losing bids tightly 2–10% above "
                                "the winner), shared ownership among top winners, "
                                "single-bid rate, and short submission windows"),
            "clusters": clusters[:n]}


def price_anomaly(category: str | None = None, n: int = 15) -> dict:
    d = get_data()
    inv, sup = d["invoices"], d["suppliers"]
    df = inv.copy()
    if category:
        df = df[df.category.str.contains(category, case=False)]
    med = inv.groupby("category").unit_price.median().rename("cat_median")
    mad = inv.groupby("category").unit_price.apply(
        lambda s: float((s - s.median()).abs().median()) or 1.0).rename("cat_mad")
    df = df.merge(med, on="category").merge(mad, on="category")
    df["pct_over"] = 100 * (df.unit_price - df.cat_median) / df.cat_median
    df["robust_z"] = (df.unit_price - df.cat_median) / (1.4826 * df.cat_mad)
    df["est_overpayment"] = ((df.unit_price - df.cat_median) * df.quantity).clip(lower=0)
    name_of = sup.set_index("supplier_id")["supplier_name"].to_dict()

    flagged = df[df.robust_z > 3].sort_values("est_overpayment", ascending=False)
    by_supplier = (flagged.groupby("supplier_id")
                   .agg(flagged_items=("invoice_id", "count"),
                        est_overpayment_sar=("est_overpayment", "sum"))
                   .sort_values("est_overpayment_sar", ascending=False))
    return {
        "model": "price_anomaly",
        "method": "robust z-score of invoice unit price vs category median "
                  "(flag when z > 3)",
        "flagged_items": int(len(flagged)),
        "estimated_total_overpayment_sar": round(float(flagged.est_overpayment.sum()), 0),
        "top_items": [
            {"invoice_id": r.invoice_id, "supplier_id": r.supplier_id,
             "supplier_name": name_of.get(r.supplier_id, r.supplier_id),
             "entity": r.entity, "category": r.category,
             "unit_price_sar": round(float(r.unit_price), 0),
             "category_median_sar": round(float(r.cat_median), 0),
             "pct_over_benchmark": round(float(r.pct_over), 1),
             "quantity": int(r.quantity),
             "est_overpayment_sar": round(float(r.est_overpayment), 0),
             "invoice_date": r.invoice_date}
            for r in flagged.head(n).itertuples()],
        "by_supplier": [
            {"supplier_id": sid, "supplier_name": name_of.get(sid, sid),
             "flagged_items": int(r["flagged_items"]),
             "est_overpayment_sar": round(float(r.est_overpayment_sar), 0)}
            for sid, r in by_supplier.head(10).iterrows()],
    }
