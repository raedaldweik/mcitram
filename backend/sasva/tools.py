"""SAS Visual Analytics toolset — view, analyze, and create dashboards.

Built against the official OpenAPI specs vendored in docs/va-api/
(visualAnalytics-v8, reports-v7, reportTransforms-v3):

* view      — render a report (or one object) to SVG/PNG server-side; the
              image is cached in-process and displayed as a live snapshot
              card in the chat UI (the LLM only ever sees metadata).
* analyze   — report summary text, object inventory, and per-object data
              export (CSV → structured rows) so the agent reasons over the
              real numbers behind the dashboard.
* create    — data-mapped report transform: copy a styled template report
              and re-bind its objects to a different CAS table with column
              mappings, saved as a new report.

Uses the same Viya environment and SASLogon session as the sasviya toolset.
"""
from __future__ import annotations

import csv as _csv
import io
import json
import urllib.parse
from typing import Optional

import httpx

from toolset import ToolSet, ToolError
from services import images
import sasviya.config as config
from sasviya.config import logger
from sasviya.tools import auth

va = ToolSet("sas_va")

_MAX_CHARS = 16000
_ALLOWED_PREFIXES = ("/reports", "/visualAnalytics", "/reportTransforms", "/folders")


async def get_token() -> str:
    if not config.VIYA_ENDPOINT:
        raise ToolError(
            "The SAS Viya environment is not configured (VIYA_ENDPOINT is "
            "empty), so Visual Analytics is unreachable. Tell the user to set "
            "the Viya environment variables.")
    return await auth.get_token()


def _client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        verify=config.SSL_VERIFY, timeout=180.0)


def _viewer_url(report_id: str) -> str:
    uri = urllib.parse.quote(f"/reports/reports/{report_id}", safe="")
    return f"{config.VIYA_ENDPOINT}/SASVisualAnalytics/?reportUri={uri}"


def _shrink(text: str, limit: int = _MAX_CHARS) -> str:
    if not text or len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated {len(text) - limit} chars]"


def _http_error(resp: httpx.Response, what: str) -> dict:
    return {"error": f"{what} failed ({resp.status_code})",
            "detail": resp.text[:500]}


async def _resolve_folder_uri(client: httpx.AsyncClient, folder: str) -> str:
    """Accepts '/folders/folders/{id}' as-is, or a path like '/Public'."""
    if folder.startswith("/folders/folders/"):
        return folder
    resp = await client.get(f"{config.VIYA_ENDPOINT}/folders/folders/@item",
                            params={"path": folder},
                            headers={"Accept": "application/json"})
    if resp.status_code >= 300:
        raise ToolError(
            f"Could not resolve folder path '{folder}' "
            f"({resp.status_code}). Pass a path like '/Public' or a full "
            f"'/folders/folders/{{id}}' URI.")
    return f"/folders/folders/{resp.json()['id']}"


# ---------------------------------------------------------------------------
# Discover & view
# ---------------------------------------------------------------------------

@va.add(
    "list_va_reports",
    "List/search SAS Visual Analytics reports (dashboards) on the connected "
    "Viya environment. Use name_filter to find a specific report (substring, "
    "case-insensitive). Returns id, name, description, and modified time — "
    "use the id with the other dashboard tools.",
    {"type": "object",
     "properties": {
         "name_filter": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum reports (default 20)."}},
     },
)
async def list_va_reports(name_filter: Optional[str] = None, limit: int = 20):
    logger.info("--- TOOL USED: list_va_reports ---")
    token = await get_token()
    params: dict = {"limit": limit, "sortBy": "modifiedTimeStamp:descending"}
    if name_filter:
        params["filter"] = f"contains(upper(name),'{name_filter.upper()}')"
    async with _client(token) as client:
        resp = await client.get(f"{config.VIYA_ENDPOINT}/reports/reports",
                                params=params,
                                headers={"Accept": "application/vnd.sas.collection+json"})
        if resp.status_code >= 300 and name_filter:
            # some deployments reject upper() in filters — retry plain
            params["filter"] = f"contains(name,'{name_filter}')"
            resp = await client.get(f"{config.VIYA_ENDPOINT}/reports/reports",
                                    params=params,
                                    headers={"Accept": "application/vnd.sas.collection+json"})
        if resp.status_code >= 300:
            return _http_error(resp, "Listing reports")
        items = resp.json().get("items", [])
    return [{"id": r.get("id"), "name": r.get("name"),
             "description": r.get("description", ""),
             "modifiedTimeStamp": r.get("modifiedTimeStamp", ""),
             "createdBy": r.get("createdBy", ""),
             "viewerUrl": _viewer_url(r.get("id", ""))} for r in items]


@va.add(
    "get_report_overview",
    "Get an overview of one report: its natural-language summary (pages, "
    "objects, data sources) plus the inventory of report objects with their "
    "names — the object names are what you pass to render_report and "
    "get_report_object_data. Call this before analyzing a dashboard.",
    {"type": "object", "properties": {"report_id": {"type": "string"}},
     "required": ["report_id"]},
)
async def get_report_overview(report_id: str):
    logger.info("--- TOOL USED: get_report_overview ---")
    token = await get_token()
    out: dict = {"reportId": report_id, "viewerUrl": _viewer_url(report_id)}
    async with _client(token) as client:
        meta = await client.get(f"{config.VIYA_ENDPOINT}/reports/reports/{report_id}",
                                headers={"Accept": "application/json"})
        if meta.status_code < 300:
            m = meta.json()
            out["name"] = m.get("name")
            out["description"] = m.get("description", "")
        summary = await client.get(
            f"{config.VIYA_ENDPOINT}/visualAnalytics/reports/{report_id}/summary",
            headers={"Accept": "text/plain"})
        if summary.status_code < 300:
            out["summary"] = _shrink(summary.text, 8000)
        else:
            out["summaryError"] = summary.text[:200]
        elements = await client.get(
            f"{config.VIYA_ENDPOINT}/reports/reports/{report_id}/content/elements",
            headers={"Accept": "application/vnd.sas.collection+json"},
            params={"characteristics": "visualElements"})
        if elements.status_code >= 300:
            elements = await client.get(
                f"{config.VIYA_ENDPOINT}/reports/reports/{report_id}/content/elements",
                headers={"Accept": "application/vnd.sas.collection+json"})
        if elements.status_code < 300:
            try:
                items = elements.json().get("items", [])
                out["objects"] = [
                    {"name": e.get("name"), "type": e.get("type"),
                     "label": e.get("label", "")}
                    for e in items if e.get("name")][:80]
            except Exception:
                pass
    return out


@va.add(
    "render_report",
    "Render a live snapshot of a Visual Analytics report — the whole report "
    "or a single object (pass report_object from get_report_overview). The "
    "snapshot is displayed automatically as an interactive card in the chat, "
    "so after calling this you don't need to describe the image — analyze "
    "the underlying numbers with get_report_object_data instead. Use "
    "whenever the user asks to SEE / show / open a dashboard.",
    {"type": "object",
     "properties": {
         "report_id": {"type": "string"},
         "report_object": {"type": "string",
                           "description": "Optional object name to render just one visual."},
         "size": {"type": "string",
                  "description": "Rendered size as 'WIDTHpx,HEIGHTpx' (default '1280px,720px')."}},
     "required": ["report_id"]},
)
async def render_report(report_id: str, report_object: Optional[str] = None,
                        size: str = "1280px,720px"):
    logger.info("--- TOOL USED: render_report (%s) ---", report_id)
    token = await get_token()
    async with _client(token) as client:
        name = None
        meta = await client.get(f"{config.VIYA_ENDPOINT}/reports/reports/{report_id}",
                                headers={"Accept": "application/json"})
        if meta.status_code < 300:
            name = meta.json().get("name")
        attempts = []
        for fmt, accept in (("svg", "image/svg+xml"), ("png", "image/png")):
            params: dict = {"size": size, "wait": 60}
            if report_object:
                params["reportObject"] = report_object
            resp = await client.get(
                f"{config.VIYA_ENDPOINT}/visualAnalytics/reports/{report_id}/{fmt}",
                params=params, headers={"Accept": accept})
            if resp.status_code < 300 and resp.content:
                image_id = images.put(resp.content, accept)
                spec = {
                    "kind": "report_image",
                    "imageUrl": f"/api/va/image/{image_id}",
                    "reportId": report_id,
                    "reportName": name or report_id,
                    "format": fmt,
                    "viewerUrl": _viewer_url(report_id),
                    "note": "The snapshot is now displayed in the chat UI.",
                }
                if report_object:
                    spec["sectionName"] = report_object
                return spec
            attempts.append({"format": fmt, "status": resp.status_code,
                             "detail": resp.text[:300]})
    return {"error": "Rendering failed for both svg and png.",
            "attempts": attempts,
            "hint": "Check the report id, or try a specific report_object "
                    "from get_report_overview."}


@va.add(
    "get_report_object_data",
    "Export the data behind ONE report object (chart/table/KPI) as "
    "structured rows — this is how you analyze what a dashboard is showing. "
    "Get object names from get_report_overview first.",
    {"type": "object",
     "properties": {
         "report_id": {"type": "string"},
         "report_object": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum rows to return (default 60)."}},
     "required": ["report_id", "report_object"]},
)
async def get_report_object_data(report_id: str, report_object: str, limit: int = 60):
    logger.info("--- TOOL USED: get_report_object_data ---")
    token = await get_token()
    async with _client(token) as client:
        resp = await client.get(
            f"{config.VIYA_ENDPOINT}/visualAnalytics/reports/{report_id}/csv",
            params={"reportObject": report_object},
            headers={"Accept": "text/csv"})
        if resp.status_code >= 300:
            return _http_error(resp, f"Exporting data for '{report_object}'")
    try:
        reader = _csv.reader(io.StringIO(resp.text))
        rows = list(reader)
    except Exception:
        return {"reportObject": report_object, "raw": _shrink(resp.text, 6000)}
    if not rows:
        return {"reportObject": report_object, "columns": [], "rows": []}
    header, data = rows[0], rows[1:]
    return {"reportObject": report_object, "columns": header,
            "rowCount": len(data),
            "rows": [dict(zip(header, r)) for r in data[:limit]]}


@va.add(
    "export_report_pdf",
    "Export a full report as a PDF and return a download link the user can "
    "open. Use when the user asks for a PDF / printable / shareable copy.",
    {"type": "object", "properties": {"report_id": {"type": "string"}},
     "required": ["report_id"]},
)
async def export_report_pdf(report_id: str):
    logger.info("--- TOOL USED: export_report_pdf ---")
    token = await get_token()
    async with _client(token) as client:
        resp = await client.get(
            f"{config.VIYA_ENDPOINT}/visualAnalytics/reports/{report_id}/pdf",
            params={"wait": 90, "includeCoverPage": True},
            headers={"Accept": "application/pdf"})
        if resp.status_code >= 300 or not resp.content:
            return _http_error(resp, "PDF export")
    image_id = images.put(resp.content, "application/pdf")
    return {"pdfUrl": f"/api/va/image/{image_id}",
            "note": "Give the user this link as markdown, e.g. "
                    f"[Download the PDF](/api/va/image/{image_id})."}


# ---------------------------------------------------------------------------
# Create — populate a styled template with real data
# ---------------------------------------------------------------------------

@va.add(
    "create_report_from_template",
    "Create a NEW dashboard by copying a styled template report and "
    "re-binding its visuals to a real CAS table (data-mapped report "
    "transform). The template's objects must be bound to a placeholder "
    "table; column_mappings maps each placeholder column to a column of the "
    "new table, e.g. [{\"originalColumn\": \"CAT1\", \"replacementColumn\": "
    "\"entity\"}]. Verify the target table's columns first "
    "(get_castable_columns), propose the mapping to the user, THEN call "
    "this. On success, render_report the new id to show the result.",
    {"type": "object",
     "properties": {
         "template_report_id": {"type": "string"},
         "new_report_name": {"type": "string"},
         "parent_folder": {"type": "string",
                           "description": "Target folder path (default '/Public') or a /folders/folders/{id} URI."},
         "original_table": {"type": "object",
                            "description": "The template's placeholder table {server, library, table}. If omitted, the tool auto-detects it from the template."},
         "replacement_table": {"type": "object",
                               "description": "The real data table {server, library, table} to bind, e.g. {\"server\": \"cas-shared-default\", \"library\": \"Public\", \"table\": \"PROCUREMENT_KPIS\"}."},
         "column_mappings": {"type": "array", "items": {"type": "object"},
                             "description": "[{originalColumn, replacementColumn}] — placeholder column → real column."}},
     "required": ["template_report_id", "new_report_name", "replacement_table",
                  "column_mappings"]},
)
async def create_report_from_template(template_report_id: str, new_report_name: str,
                                      replacement_table: dict, column_mappings: list,
                                      parent_folder: str = "/Public",
                                      original_table: Optional[dict] = None):
    logger.info("--- TOOL USED: create_report_from_template ---")
    token = await get_token()
    async with _client(token) as client:
        folder_uri = await _resolve_folder_uri(client, parent_folder)

        if not original_table:
            original_table = await _detect_template_table(client, template_report_id)
            if not original_table:
                return {"error": "Could not auto-detect the template's data "
                                 "source. Pass original_table as {server, "
                                 "library, table} (see get_report_overview's "
                                 "summary for the template's data source)."}

        for key in ("server", "library", "table"):
            if not replacement_table.get(key):
                raise ToolError(f"replacement_table.{key} is required "
                                f"(got {replacement_table}).")

        replacements = []
        for m in column_mappings or []:
            if not isinstance(m, dict) or not m.get("replacementColumn"):
                raise ToolError("Each column mapping needs at least "
                                "replacementColumn (plus originalColumn or "
                                "originalName).")
            entry = {"replacementColumn": m["replacementColumn"]}
            if m.get("originalColumn"):
                entry["originalColumn"] = m["originalColumn"]
            if m.get("originalName"):
                entry["originalName"] = m["originalName"]
            replacements.append(entry)

        body = {
            "inputReportUri": f"/reports/reports/{template_report_id}",
            "resultReportName": new_report_name,
            "resultParentFolderUri": folder_uri,
            "dataSources": [
                {"purpose": "original",
                 "namePattern": "serverLibraryTable",
                 "server": original_table.get("server", "cas-shared-default"),
                 "library": original_table.get("library", "Public"),
                 "table": original_table.get("table")},
                {"purpose": "replacement",
                 "namePattern": "serverLibraryTable",
                 "server": replacement_table["server"],
                 "library": replacement_table["library"],
                 "table": replacement_table["table"],
                 "dataItemReplacements": replacements},
            ],
        }
        resp = await client.post(
            f"{config.VIYA_ENDPOINT}/reportTransforms/dataMappedReports",
            params={"useSavedReport": "true", "saveResult": "true",
                    "failOnDataSourceError": "false", "validate": "true"},
            json=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/vnd.sas.report.transform+json"})
        if resp.status_code >= 300:
            return {"error": f"Data-mapped transform failed ({resp.status_code})",
                    "detail": resp.text[:600],
                    "hint": "Check that the template's objects are bound to "
                            "the original_table and every mapped column "
                            "exists on both sides."}
        result = resp.json()

    new_report = result.get("resultReport") or {}
    new_id = new_report.get("id")
    out = {
        "status": "created",
        "reportId": new_id,
        "reportName": new_report.get("name", new_report_name),
        "folder": parent_folder,
        "viewerUrl": _viewer_url(new_id) if new_id else None,
        "evaluationStatus": result.get("evaluationStatus"),
        "messages": [m.get("message") if isinstance(m, dict) else str(m)
                     for m in (result.get("messages") or [])][:10],
        "nextStep": "Call render_report with this reportId to show the new "
                    "dashboard in the chat, then suggest enhancements.",
    }
    if result.get("errorMessages"):
        out["errorMessages"] = [str(m)[:300] for m in result["errorMessages"]][:5]
    return out


async def _detect_template_table(client: httpx.AsyncClient,
                                 report_id: str) -> Optional[dict]:
    """Best-effort: pull the first CAS data source out of the template's BIRD
    content (dicts carrying server/library/table or casResource attributes)."""
    resp = await client.get(
        f"{config.VIYA_ENDPOINT}/reports/reports/{report_id}/content",
        headers={"Accept": "application/vnd.sas.report.content+json"})
    if resp.status_code >= 300:
        return None
    try:
        content = resp.json()
    except Exception:
        return None

    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 12 or found:
            return
        if isinstance(node, dict):
            keys = {k.lower() for k in node.keys()}
            if {"server", "library", "table"} <= keys:
                found.append({"server": node.get("server") or node.get("Server"),
                              "library": node.get("library") or node.get("Library"),
                              "table": node.get("table") or node.get("Table")})
                return
            # casResource form: {"cas": {"server":..., "library":..., "table":...}}
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(content)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------

@va.add(
    "va_api_request",
    "Generic REST call against the reporting services (/reports, "
    "/visualAnalytics, /reportTransforms, /folders) — the escape hatch for "
    "advanced operations such as reading raw report content "
    "(GET /reports/reports/{id}/content with accept "
    "'application/vnd.sas.report.content+json') or the VA operations API. "
    "Use write methods (POST/PUT/DELETE) only after the user explicitly "
    "confirms, and never delete anything you did not create this "
    "conversation.",
    {"type": "object",
     "properties": {
         "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
         "path": {"type": "string"},
         "params": {"type": "object"},
         "body": {"type": "object"},
         "accept": {"type": "string", "description": "Accept header override."},
         "content_type": {"type": "string", "description": "Content-Type override for POST/PUT."}},
     "required": ["method", "path"]},
)
async def va_api_request(method: str, path: str, params: Optional[dict] = None,
                         body: Optional[dict] = None, accept: Optional[str] = None,
                         content_type: Optional[str] = None):
    logger.info("--- TOOL USED: va_api_request (%s %s) ---", method, path)
    method = (method or "GET").upper()
    if not any(path.startswith(p) for p in _ALLOWED_PREFIXES):
        raise ToolError(f"Path must start with one of "
                        f"{', '.join(_ALLOWED_PREFIXES)} — got '{path}'.")
    token = await get_token()
    headers = {"Accept": accept or "application/json"}
    kwargs: dict = {"params": params or {}, "headers": headers}
    if method in ("POST", "PUT") and body is not None:
        headers["Content-Type"] = content_type or "application/json"
        kwargs["content"] = json.dumps(body)
    async with _client(token) as client:
        resp = await client.request(method, f"{config.VIYA_ENDPOINT}{path}", **kwargs)
        out: dict = {"status": resp.status_code, "path": path}
        try:
            payload = resp.json()
            out["data"] = json.loads(_shrink(json.dumps(payload, default=str)))\
                if len(json.dumps(payload, default=str)) > _MAX_CHARS else payload
        except Exception:
            out["data"] = _shrink(resp.text)
        return out
