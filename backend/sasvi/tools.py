"""SAS Visual Investigator toolset — alert triage and entity investigation.

Implements the scope planned in the SAS_VI_MCP roadmap (search entities, read
alerts and workflow state, surface relationships) against VI's REST services:

* ``svi-alert``   — alerts raised by detection scenarios (triage queue)
* ``svi-datahub`` — indexed entities/documents and their relationships

The VI REST surface varies between releases and deployments, so the specific
tools are written defensively (candidate endpoint fallbacks, shaped errors the
agent can react to) and ``vi_api_request`` is included as a generic explorer:
if a specific tool's path doesn't match this deployment, the agent can probe
the API and still complete the task.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from saslogon import SASLogonAuth
from toolset import ToolSet, ToolError
from . import config
from .config import logger

auth = SASLogonAuth(
    endpoint=config.VI_ENDPOINT,
    client_id=config.VI_CLIENT_ID,
    client_secret=config.VI_CLIENT_SECRET,
    refresh_token=config.VI_REFRESH_TOKEN,
    username=config.VI_USERNAME,
    password=config.VI_PASSWORD,
    verify=config.VI_SSL_VERIFY,
    label="SAS Visual Investigator",
)

vi = ToolSet("sas_vi")

_ALLOWED_PREFIXES = ("/svi-", "/SASVisualInvestigator", "/casManagement",
                     "/reports", "/search")
_MAX_CHARS = 18000


async def get_token() -> str:
    if not config.VI_ENDPOINT:
        raise ToolError(
            "The Visual Investigator environment is not configured "
            "(VI_ENDPOINT is empty). Tell the user to set VI_ENDPOINT plus "
            "credentials (VI_REFRESH_TOKEN, or VI_USERNAME/VI_PASSWORD).")
    return await auth.get_token()


def _client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        verify=config.VI_SSL_VERIFY, timeout=120.0)


def _shrink(value: Any, limit: int = _MAX_CHARS) -> Any:
    """Cap a JSON payload's size so one verbose VI response can't blow up the
    agent's context. Returns the value unchanged when it fits."""
    try:
        text = json.dumps(value, default=str)
    except Exception:
        return str(value)[:limit]
    if len(text) <= limit:
        return value
    return {"truncated": True,
            "note": f"Response was {len(text)} chars; showing the first part. "
                    f"Ask for fewer items or specific fields.",
            "preview": text[:limit]}


async def _try_get(client: httpx.AsyncClient, paths: list[str],
                   params: Optional[dict] = None) -> dict:
    """GET the first candidate path that answers 2xx; report every attempt
    otherwise so the agent can adjust (e.g. via vi_api_request)."""
    attempts = []
    for path in paths:
        try:
            resp = await client.get(f"{config.VI_ENDPOINT}{path}",
                                    params=params or {},
                                    headers={"Accept": "application/json"},
                                    follow_redirects=True)
        except httpx.HTTPError as e:
            attempts.append({"path": path, "error": str(e)})
            continue
        if resp.status_code < 300:
            try:
                return {"ok": True, "path": path, "data": resp.json()}
            except Exception:
                return {"ok": True, "path": path, "data": resp.text[:_MAX_CHARS]}
        attempts.append({"path": path, "status": resp.status_code,
                         "detail": resp.text[:300]})
    return {"ok": False, "attempts": attempts,
            "hint": "None of the candidate endpoints answered. Use "
                    "vi_api_request to probe this deployment's API surface."}


def _shape_alert(a: dict) -> dict:
    """Trim an alert record to what triage needs, tolerating field-name
    differences across VI versions."""
    def pick(*names):
        for n in names:
            if a.get(n) is not None:
                return a.get(n)
        return None
    shaped = {
        "id": pick("id", "alertId"),
        "label": pick("label", "name", "displayName", "title"),
        "score": pick("score", "totalScore", "alertScore"),
        "status": pick("status", "state", "dispositionStatus"),
        "queue": pick("queueName", "queue", "queueId"),
        "entityType": pick("entityType", "objectTypeName", "documentType"),
        "entityId": pick("entityId", "objectId", "documentId"),
        "entityLabel": pick("entityLabel", "objectLabel"),
        "createdAt": pick("createdTimestamp", "creationTimeStamp", "createdAt"),
        "modifiedAt": pick("modifiedTimestamp", "modifiedTimeStamp"),
        "assignedTo": pick("assignedTo", "owner", "assignee"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    # keep any scenario/reason info — it's the heart of triage
    for key in ("scenarios", "scenarioNames", "reasons", "contributingScenarios"):
        if a.get(key) is not None:
            shaped[key] = a[key]
            break
    return shaped or a


# ---------------------------------------------------------------------------


@vi.add(
    "get_investigation_scope",
    "Return this assistant's investigation scope: what is deployed on the "
    "connected SAS Visual Investigator environment and whether the connection "
    "is configured. Call this first in a new conversation.",
    {"type": "object", "properties": {}},
)
async def get_investigation_scope():
    logger.info("--- TOOL USED: get_investigation_scope ---")
    return {
        "environment": config.VI_ENDPOINT or "(not configured)",
        "configured": config.configured(),
        "useCase": config.VI_USE_CASE,
        "services": {
            "svi-alert": "alerts raised by detection scenarios (triage queue)",
            "svi-datahub": "indexed entities/documents, search, relationships",
        },
        "notes": (
            "Alert and entity field names vary by VI release. If a specific "
            "tool reports failed endpoint attempts, fall back to "
            "vi_api_request to explore the API and adapt."),
    }


@vi.add(
    "search_alerts",
    "List/search alerts in the Visual Investigator triage queue. Returns "
    "shaped alert records (id, label, score, status, entity, scenarios). Use "
    "this to build a work list, find high-score alerts, or locate the alert "
    "for a specific supplier/entity.",
    {"type": "object",
     "properties": {
         "limit": {"type": "integer", "description": "Maximum alerts (default 25)."},
         "start": {"type": "integer", "description": "Offset for paging (default 0)."},
         "sort_by_score": {"type": "boolean", "description": "Sort by score descending when supported (default true)."}},
     },
)
async def search_alerts(limit: int = 25, start: int = 0, sort_by_score: bool = True):
    logger.info("--- TOOL USED: search_alerts ---")
    token = await get_token()
    params = {"start": start, "limit": limit}
    if sort_by_score:
        params["sortBy"] = "score:descending"
    async with _client(token) as client:
        result = await _try_get(client, ["/svi-alert/alerts"], params=params)
        if not result.get("ok") and sort_by_score:
            # some releases reject unknown sort keys — retry without it
            result = await _try_get(client, ["/svi-alert/alerts"],
                                    params={"start": start, "limit": limit})
    if not result.get("ok"):
        return result
    data = result["data"]
    items = data.get("items", data if isinstance(data, list) else [])
    return _shrink({"count": data.get("count", len(items)) if isinstance(data, dict) else len(items),
                    "alerts": [_shape_alert(a) for a in items]})


@vi.add(
    "get_alert",
    "Get the full detail of one alert by ID: scores, contributing scenarios, "
    "disposition/workflow state, and the flagged entity.",
    {"type": "object", "properties": {"alert_id": {"type": "string"}},
     "required": ["alert_id"]},
)
async def get_alert(alert_id: str):
    logger.info("--- TOOL USED: get_alert ---")
    token = await get_token()
    async with _client(token) as client:
        result = await _try_get(client, [f"/svi-alert/alerts/{alert_id}"])
    if not result.get("ok"):
        return result
    return _shrink(result["data"])


@vi.add(
    "get_alerting_events",
    "Get the alerting events (scenario fire-events) behind one alert — the "
    "specific detections and their contributions to the score. Essential for "
    "explaining WHY an alert fired and judging false positives.",
    {"type": "object",
     "properties": {
         "alert_id": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum events (default 25)."}},
     "required": ["alert_id"]},
)
async def get_alerting_events(alert_id: str, limit: int = 25):
    logger.info("--- TOOL USED: get_alerting_events ---")
    token = await get_token()
    async with _client(token) as client:
        result = await _try_get(client, [
            f"/svi-alert/alerts/{alert_id}/alertingEvents",
            f"/svi-alert/alerts/{alert_id}/events",
        ], params={"limit": limit})
    if not result.get("ok"):
        return result
    return _shrink(result["data"])


@vi.add(
    "search_entities",
    "Free-text search across the entities indexed in Visual Investigator's "
    "data hub (suppliers, persons, transactions, tenders, ...). Use to find "
    "an entity by name or attribute before pulling its details.",
    {"type": "object",
     "properties": {
         "query": {"type": "string", "description": "Free-text search query."},
         "entity_types": {"type": "array", "items": {"type": "string"},
                          "description": "Optional list of entity/document type names to restrict to."},
         "limit": {"type": "integer", "description": "Maximum hits (default 20)."}},
     "required": ["query"]},
)
async def search_entities(query: str, entity_types: Optional[list] = None,
                          limit: int = 20):
    logger.info("--- TOOL USED: search_entities (%s) ---", query)
    token = await get_token()
    body: dict = {"query": query, "start": 0, "limit": limit}
    if entity_types:
        body["documentTypes"] = entity_types
    attempts = []
    async with _client(token) as client:
        for path, payload in (("/svi-datahub/search", body),
                              ("/svi-datahub/documents/search", body)):
            try:
                resp = await client.post(f"{config.VI_ENDPOINT}{path}",
                                         json=payload,
                                         headers={"Accept": "application/json"})
            except httpx.HTTPError as e:
                attempts.append({"path": path, "error": str(e)})
                continue
            if resp.status_code < 300:
                try:
                    return _shrink({"ok": True, "path": path, "data": resp.json()})
                except Exception:
                    return {"ok": True, "path": path, "data": resp.text[:_MAX_CHARS]}
            attempts.append({"path": path, "status": resp.status_code,
                             "detail": resp.text[:300]})
        # last resort: GET with q param
        result = await _try_get(client, ["/svi-datahub/search"],
                                params={"q": query, "limit": limit})
        if result.get("ok"):
            return _shrink(result)
    return {"ok": False, "attempts": attempts,
            "hint": "Search endpoint differs on this deployment — probe with "
                    "vi_api_request."}


@vi.add(
    "get_entity",
    "Read one entity/document from the data hub by type and ID (e.g. a "
    "supplier's full record).",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string", "description": "Entity/document type name as defined in VI (e.g. 'supplier')."},
         "entity_id": {"type": "string"}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity(entity_type: str, entity_id: str):
    logger.info("--- TOOL USED: get_entity ---")
    token = await get_token()
    async with _client(token) as client:
        result = await _try_get(client, [
            f"/svi-datahub/documents/{entity_type}/{entity_id}",
        ])
    if not result.get("ok"):
        return result
    return _shrink(result["data"])


@vi.add(
    "get_entity_relationships",
    "Get the relationships/network around one entity (who is linked to whom) "
    "— e.g. a supplier's related persons, addresses, tenders, payments. Use "
    "for link analysis when triaging an alert.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum related records (default 30)."}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity_relationships(entity_type: str, entity_id: str, limit: int = 30):
    logger.info("--- TOOL USED: get_entity_relationships ---")
    token = await get_token()
    base = f"/svi-datahub/documents/{entity_type}/{entity_id}"
    async with _client(token) as client:
        result = await _try_get(client, [
            f"{base}/relationships",
            f"{base}/links",
            f"{base}/related",
        ], params={"limit": limit})
    if not result.get("ok"):
        return result
    return _shrink(result["data"])


@vi.add(
    "vi_api_request",
    "Generic Visual Investigator REST call — the exploration escape hatch "
    "when a dedicated tool's endpoint doesn't match this deployment. GET for "
    "reading; POST only for search-style endpoints or, when the user has "
    "explicitly confirmed, workflow actions (e.g. updating a disposition). "
    "Path must start with /svi- (e.g. /svi-alert/alerts, /svi-datahub/search). "
    "Never guess destructive endpoints.",
    {"type": "object",
     "properties": {
         "method": {"type": "string", "enum": ["GET", "POST", "PUT"]},
         "path": {"type": "string", "description": "Path starting with /svi-…"},
         "params": {"type": "object", "description": "Optional query parameters."},
         "body": {"type": "object", "description": "Optional JSON body for POST/PUT."}},
     "required": ["method", "path"]},
)
async def vi_api_request(method: str, path: str, params: Optional[dict] = None,
                         body: Optional[dict] = None):
    logger.info("--- TOOL USED: vi_api_request (%s %s) ---", method, path)
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT"):
        raise ToolError("method must be GET, POST, or PUT.")
    if not any(path.startswith(p) for p in _ALLOWED_PREFIXES):
        raise ToolError(
            f"Path must start with one of {', '.join(_ALLOWED_PREFIXES)} — "
            f"got '{path}'.")
    token = await get_token()
    async with _client(token) as client:
        resp = await client.request(
            method, f"{config.VI_ENDPOINT}{path}", params=params or {},
            json=body if method in ("POST", "PUT") else None,
            headers={"Accept": "application/json"}, follow_redirects=True)
        out: dict = {"status": resp.status_code, "path": path}
        try:
            out["data"] = resp.json()
        except Exception:
            out["data"] = resp.text[:_MAX_CHARS]
        return _shrink(out)
