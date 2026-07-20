"""Tool bindings for the procurement-integrity use-case agent.

Mirrors the scoped use-case MCP pattern (SAS_Use_Case): a small, focused tool
set — get_use_case grounding, structured queries, and the ready models — so
the agent stays a reliable expert on its dataset.
"""
from __future__ import annotations

from typing import Optional

from toolset import ToolSet
from . import data as D
from . import models as M

procurement = ToolSet("procurement_usecase")


@procurement.add(
    "get_use_case",
    "Return this assistant's use case: the procurement datasets it is an "
    "expert on (schemas + categorical values), the ready analytical models, "
    "and headline KPIs. Call this first in a new conversation.",
    {"type": "object", "properties": {}},
)
async def get_use_case():
    return {
        "useCaseName": "SAS Procurement Integrity Monitor",
        "description": (
            "Government procurement oversight for the demo country entities: tenders, "
            "bids, suppliers, invoices and integrity alerts (amounts in USD). "
            "Includes ready models for supplier risk scoring, bid-rigging "
            "screening, and price-anomaly detection."),
        "datasets": {k: D.describe_dataset(k)
                     for k in ("suppliers", "tenders", "bids", "invoices", "alerts")},
        "models": {
            "supplier_risk": "composite 0-100 integrity risk score per supplier "
                             "(views: summary | top_suppliers | by_group)",
            "bid_rigging": "collusion screen across entity × category markets",
            "price_anomaly": "unit-price outliers vs category benchmarks",
        },
        "kpis": D.kpis(),
        "direct_award_threshold_sar": D.DIRECT_AWARD_THRESHOLD,
    }


@procurement.add(
    "procurement_query",
    "Query the procurement datasets (suppliers, tenders, bids, invoices, "
    "alerts) with structured operations. Query types: describe_dataset "
    "(schema/values — start here if unsure), kpis (headline numbers), "
    "filter_rows (conditions; optional aggregate {column, func} or "
    "select_columns), groupby_aggregate (requires group_by; optional metric + "
    "func), top_n (requires sort_by), time_series (monthly by default; "
    "optional split_by, metric+func), histogram (requires column). `filters` "
    "is a list of {column, op, value} with ops ==, !=, >, <, >=, <=, between, "
    "contains, in, not_in.",
    {"type": "object",
     "properties": {
         "query_type": {"type": "string",
                        "enum": ["describe_dataset", "kpis", "filter_rows",
                                 "groupby_aggregate", "top_n", "time_series",
                                 "histogram"]},
         "dataset": {"type": "string",
                     "enum": ["suppliers", "tenders", "bids", "invoices", "alerts"]},
         "filters": {"type": "array", "items": {"type": "object"}},
         "select_columns": {"type": "array", "items": {"type": "string"}},
         "aggregate": {"type": "object",
                       "description": "{column, func} — func: mean|median|sum|min|max|std"},
         "group_by": {"type": "string"},
         "metric": {"type": "string"},
         "func": {"type": "string"},
         "sort_by": {"type": "string"},
         "n": {"type": "integer"},
         "ascending": {"type": "boolean"},
         "split_by": {"type": "string"},
         "freq": {"type": "string", "enum": ["D", "W", "M"]},
         "column": {"type": "string"},
         "bins": {"type": "integer"},
         "limit": {"type": "integer"}},
     "required": ["query_type"]},
)
async def procurement_query(query_type: str, dataset: str = "tenders",
                            filters: Optional[list] = None,
                            select_columns: Optional[list] = None,
                            aggregate: Optional[dict] = None,
                            group_by: Optional[str] = None,
                            metric: Optional[str] = None,
                            func: str = "count",
                            sort_by: Optional[str] = None,
                            n: int = 10, ascending: bool = False,
                            split_by: Optional[str] = None, freq: str = "M",
                            column: Optional[str] = None, bins: int = 10,
                            limit: int = 20):
    if query_type == "describe_dataset":
        return D.describe_dataset(dataset)
    if query_type == "kpis":
        return D.kpis()
    if query_type == "filter_rows":
        return D.filter_rows(dataset, filters, select_columns, aggregate, limit)
    if query_type == "groupby_aggregate":
        return D.groupby_aggregate(dataset, group_by or "", metric, func, filters, n or 30)
    if query_type == "top_n":
        return D.top_n(dataset, sort_by or "", n, ascending, filters, select_columns)
    if query_type == "time_series":
        return D.time_series(dataset, freq, split_by, filters, metric, func)
    if query_type == "histogram":
        return D.histogram(dataset, column or "", bins, filters)
    return {"error": f"unknown query_type: {query_type}"}


@procurement.add(
    "run_model",
    "Run one of the use case's ready analytical models: supplier_risk "
    "(composite 0-100 integrity score; view: summary | top_suppliers | "
    "by_group with group_by region|primary_category), bid_rigging (collusion "
    "screen across entity × category markets; optional entity/category "
    "filter), price_anomaly (unit-price outliers vs category benchmarks; "
    "optional category filter). Always base findings and recommendations on "
    "these results, never on invented numbers.",
    {"type": "object",
     "properties": {
         "model": {"type": "string",
                   "enum": ["supplier_risk", "bid_rigging", "price_anomaly"]},
         "view": {"type": "string", "enum": ["summary", "top_suppliers", "by_group"]},
         "group_by": {"type": "string"},
         "entity": {"type": "string"},
         "category": {"type": "string"},
         "n": {"type": "integer"}},
     "required": ["model"]},
)
async def run_model(model: str, view: str = "summary",
                    group_by: Optional[str] = None, entity: Optional[str] = None,
                    category: Optional[str] = None, n: int = 10):
    if model == "supplier_risk":
        return M.supplier_risk(view, group_by, n)
    if model == "bid_rigging":
        return M.bid_rigging(entity, category, n)
    if model == "price_anomaly":
        return M.price_anomaly(category, n)
    return {"error": f"unknown model: {model}"}
