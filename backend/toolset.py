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
    ct = (chart_type or "").strip().lower()
    if ct not in _CHART_TYPES:
        raise ToolError(f"chart_type must be one of {', '.join(_CHART_TYPES)}; got '{chart_type}'.")
    if not isinstance(data, list) or not data:
        raise ToolError("data must be a non-empty list of row objects.")
    if not isinstance(data[0], dict):
        raise ToolError("each item in data must be an object (key/value row).")
    if not y_keys:
        raise ToolError("y_keys must list at least one field to plot.")
    keys = list(data[0].keys())
    missing = [k for k in [x_key, *y_keys] if k not in keys]
    if missing:
        raise ToolError(
            f"these keys are not present in the data rows: {', '.join(missing)}. "
            f"Available keys: {', '.join(keys)}.")
    return {
        "kind": "chart",
        "type": ct,
        "title": title,
        "subtitle": subtitle,
        "data": data,
        "xKey": x_key,
        "yKeys": list(y_keys),
        "stacked": bool(stacked),
    }
