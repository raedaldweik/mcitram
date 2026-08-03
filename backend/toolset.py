"""Tool plumbing for the agent runner.

A ToolSet is a named registry of async tool functions plus their Anthropic
tool definitions (name / description / input_schema). Agents are wired to one
or more toolsets (optionally a subset of the tools in each); the runner merges
the specs into the `tools` parameter of the Messages API call and dispatches
`tool_use` blocks back to the registered functions.

The tool names, descriptions, and behaviors mirror the MCP servers this repo
vendors (sas-mcp-server, the Web_Search news server, and the planned VI
server) — they run in-process here so the whole app ships as one container.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Optional


class ToolError(Exception):
    """A tool failed in a way the agent should see and react to."""


class ToolSet:
    def __init__(self, name: str):
        self.name = name
        self._fns: dict[str, Callable] = {}
        self._specs: dict[str, dict] = {}

    def add(self, name: str, description: str, input_schema: dict):
        """Register an async function as a tool."""
        def deco(fn):
            self._fns[name] = fn
            self._specs[name] = {
                "name": name,
                "description": description,
                "input_schema": input_schema,
            }
            return fn
        return deco

    @property
    def tool_names(self) -> list[str]:
        return list(self._specs.keys())

    def specs(self, only: Optional[list[str]] = None) -> list[dict]:
        names = only if only is not None else self.tool_names
        return [self._specs[n] for n in names if n in self._specs]

    def has(self, name: str) -> bool:
        return name in self._fns

    async def execute(self, name: str, args: dict) -> Any:
        fn = self._fns[name]
        result = fn(**(args or {}))
        if inspect.isawaitable(result):
            result = await result
        return result


# ---------------------------------------------------------------------------
# Shared visualization tool (identical contract to the MCP servers'
# render_chart — the frontend detects the `kind: "chart"` spec in tool
# outputs and draws it with the in-house SVG ChartCard).
# ---------------------------------------------------------------------------

_CHART_TYPES = ("bar", "line", "area", "pie", "scatter")

charts = ToolSet("charts")


def _validate_chart_payload(chart_type: str, data: list, x_key: str,
                            y_keys: list, where: str = "") -> None:
    ctx = f" (in {where})" if where else ""
    ct = (chart_type or "").strip().lower()
    if ct not in _CHART_TYPES:
        raise ToolError(f"chart_type must be one of {', '.join(_CHART_TYPES)}; got '{chart_type}'{ctx}.")
    if not isinstance(data, list) or not data:
        raise ToolError(f"data must be a non-empty list of row objects{ctx}.")
    if not isinstance(data[0], dict):
        raise ToolError(f"each item in data must be an object (key/value row){ctx}.")
    if not y_keys:
        raise ToolError(f"y_keys must list at least one field to plot{ctx}.")
    keys = list(data[0].keys())
    missing = [k for k in [x_key, *y_keys] if k not in keys]
    if missing:
        raise ToolError(
            f"these keys are not present in the data rows{ctx}: {', '.join(missing)}. "
            f"Available keys: {', '.join(keys)}.")


@charts.add(
    "render_chart",
    "Render an interactive chart in the chat UI. Use whenever the user asks to "
    "show / plot / visualize / graph / compare data, or when a chart makes the "
    "answer clearer than text. Call this AFTER fetching the rows with the data "
    "tools, then pass the rows in as `data`. Keep `data` small — aggregate or "
    "limit to just the rows you want to chart (e.g. top 10). The chart is drawn "
    "by the user interface from the spec this returns.",
    {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": list(_CHART_TYPES),
                           "description": "One of bar, line, area, pie, scatter."},
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "data": {"type": "array", "items": {"type": "object"},
                     "description": "Row objects, e.g. [{\"month\": \"Jan\", \"sales\": 120}]."},
            "x_key": {"type": "string",
                      "description": "Field for the x-axis / category (for pie, the slice label)."},
            "y_keys": {"type": "array", "items": {"type": "string"},
                       "description": "Field(s) plotted as series / values."},
            "stacked": {"type": "boolean", "description": "For bar/area, stack the series."},
        },
        "required": ["chart_type", "title", "data", "x_key", "y_keys"],
    },
)
async def render_chart(chart_type: str, title: str, data: list, x_key: str,
                       y_keys: list, subtitle: str = "", stacked: bool = False) -> dict:
    _validate_chart_payload(chart_type, data, x_key, y_keys)
    return {
        "kind": "chart",
        "type": (chart_type or "").strip().lower(),
        "title": title,
        "subtitle": subtitle,
        "data": data,
        "xKey": x_key,
        "yKeys": list(y_keys),
        "stacked": bool(stacked),
    }


@charts.add(
    "render_report",
    "Render a full consultant-style executive report as a styled document "
    "card in the chat — title block, KPI tiles, sections with prose / tables "
    "/ chart exhibits, and a prioritized recommendations list. Use when the "
    "user asks for a report, brief, one-pager, or executive summary "
    "document. Gather ALL the evidence with the data tools FIRST, then call "
    "this ONCE with the complete report. Charts inside sections render "
    "inline as exhibits — do not also call render_chart for them. Section "
    "bodies accept markdown (bold, bullets). Write every string in the "
    "user's language.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Report title, e.g. 'Rice Supply Risk — Strategic Reserve Outlook'."},
            "subtitle": {"type": "string", "description": "One-line scope/date-range strapline."},
            "prepared_for": {"type": "string", "description": "Audience line, e.g. 'Prepared for the MCIT Strategic Reserve Committee'."},
            "kpis": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
                "label": {"type": "string"},
                "value": {"type": "string", "description": "Headline figure, short — e.g. '14.6M kg' or 'Sep 2026'."},
                "sub": {"type": "string", "description": "One-line qualifier under the value."},
                "tone": {"type": "string", "enum": ["ok", "warn", "alarm", "neutral"]}},
                "required": ["label", "value"]},
                "description": "3-6 headline stat tiles shown under the title."},
            "sections": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "object", "properties": {
                "heading": {"type": "string"},
                "body": {"type": "string", "description": "Tight consultant prose (markdown allowed)."},
                "table": {"type": "object", "properties": {
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "rows": {"type": "array", "items": {"type": "array"}}},
                    "description": "Optional small data table."},
                "chart": {"type": "object", "properties": {
                    "chart_type": {"type": "string", "enum": list(_CHART_TYPES)},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "data": {"type": "array", "items": {"type": "object"}},
                    "x_key": {"type": "string"},
                    "y_keys": {"type": "array", "items": {"type": "string"}},
                    "stacked": {"type": "boolean"}},
                    "description": "Optional chart exhibit rendered inside this section."}},
                "required": ["heading", "body"]}},
            "recommendations": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
                "title": {"type": "string"},
                "detail": {"type": "string"},
                "priority": {"type": "string", "description": "Short priority label in the user's language, e.g. 'Now' / 'Next quarter' / 'فوراً'."}},
                "required": ["title"]},
                "description": "Prioritized action list closing the report."},
            "sources": {"type": "string", "description": "Data provenance line, e.g. 'Live SAS model commodity_demand_prediction · deterministic reserve engine · prices are editable assumptions'."},
        },
        "required": ["title", "sections"],
    },
)
async def render_report(title: str, sections: list, subtitle: str = "",
                        prepared_for: str = "", kpis: list = None,
                        recommendations: list = None, sources: str = "") -> dict:
    from datetime import date
    if not isinstance(sections, list) or not sections:
        raise ToolError("sections must be a non-empty list.")
    out_sections = []
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict) or not sec.get("heading") or not sec.get("body"):
            raise ToolError(f"section {i + 1} needs both 'heading' and 'body'.")
        entry = {"heading": sec["heading"], "body": sec["body"]}
        table = sec.get("table")
        if table:
            cols, rows = table.get("columns"), table.get("rows")
            if not cols or not isinstance(rows, list):
                raise ToolError(f"section {i + 1}: table needs 'columns' and 'rows'.")
            entry["table"] = {"columns": cols, "rows": rows}
        chart = sec.get("chart")
        if chart:
            _validate_chart_payload(chart.get("chart_type"), chart.get("data"),
                                    chart.get("x_key"), chart.get("y_keys"),
                                    where=f"section {i + 1} chart")
            # kind 'report_chart' so the standalone chart extractor doesn't
            # ALSO render it at the bottom of the reply
            entry["chart"] = {
                "kind": "report_chart",
                "type": chart["chart_type"].strip().lower(),
                "title": chart.get("title", ""),
                "subtitle": chart.get("subtitle", ""),
                "data": chart["data"],
                "xKey": chart["x_key"],
                "yKeys": list(chart["y_keys"]),
                "stacked": bool(chart.get("stacked", False)),
            }
        out_sections.append(entry)
    out_kpis = []
    for k in (kpis or []):
        if not isinstance(k, dict) or not k.get("label") or not k.get("value"):
            raise ToolError("each kpi needs 'label' and 'value'.")
        tone = k.get("tone", "neutral")
        out_kpis.append({"label": k["label"], "value": k["value"],
                         "sub": k.get("sub", ""),
                         "tone": tone if tone in ("ok", "warn", "alarm", "neutral") else "neutral"})
    out_recs = []
    for r in (recommendations or []):
        if not isinstance(r, dict) or not r.get("title"):
            raise ToolError("each recommendation needs a 'title'.")
        out_recs.append({"title": r["title"], "detail": r.get("detail", ""),
                         "priority": r.get("priority", "")})
    return {
        "kind": "exec_report",
        "title": title,
        "subtitle": subtitle,
        "preparedFor": prepared_for,
        "date": date.today().isoformat(),
        "kpis": out_kpis,
        "sections": out_sections,
        "recommendations": out_recs,
        "sources": sources,
    }
