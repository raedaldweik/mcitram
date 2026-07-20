# Vendored from sas-mcp-server (Copyright © 2025, SAS Institute Inc.,
# Apache-2.0), adapted from FastMCP registration to the in-process ToolSet
# used by this app's agents. Tool names, arguments, and behavior match the
# MCP server so the same skills transfer 1:1 to a RAM + Viya-MCP deployment.

"""SAS Viya toolset: data discovery, SAS code execution, structured SQL
queries, synthetic data generation, files, batch jobs, AutoML (ML pipeline
automation), model management, real-time scoring, and data insights."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Optional

import httpx as _httpx

from saslogon import SASLogonAuth
from toolset import ToolSet, ToolError
from . import config
from .config import MAX_SAS_OUTPUT_CHARS, logger
from .viya_utils import (
    _delete_resource,
    _get_json,
    _get_paged_items,
    _make_client,
    _post_json,
    fetch_table_columns,
    run_one_snippet,
    run_query_rows,
)

import os

MAX_SYNTHETIC_ROWS = int(os.getenv("MAX_SYNTHETIC_ROWS", "1000000"))

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
_SYNTH_TYPES = ("id", "int", "float", "category", "bool", "date")

auth = SASLogonAuth(
    endpoint=config.VIYA_ENDPOINT,
    client_id=config.CLIENT_ID,
    client_secret=config.CLIENT_SECRET,
    refresh_token=config.VIYA_REFRESH_TOKEN,
    username=config.VIYA_USERNAME,
    password=config.VIYA_PASSWORD,
    verify=config.SSL_VERIFY,
    label="SAS Viya",
)

viya = ToolSet("sas_viya")


async def get_token() -> str:
    if not config.VIYA_ENDPOINT:
        raise ToolError(
            "The SAS Viya environment is not configured (VIYA_ENDPOINT is "
            "empty). Tell the user to set VIYA_ENDPOINT plus credentials "
            "(VIYA_REFRESH_TOKEN, or VIYA_USERNAME/VIYA_PASSWORD) in the "
            "deployment environment variables.")
    return await auth.get_token()


def _truncate_output(text, limit=MAX_SAS_OUTPUT_CHARS):
    """Cap large SAS log/listing text so it can't overflow the agent's context."""
    if not text or limit <= 0 or len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n\n...[truncated {omitted} characters to fit the model "
        f"context — re-run a narrower query (fewer columns/rows) for full "
        f"detail]...\n\n{text[-tail:]}"
    )


def _sas_quote(value) -> str:
    s = str(value).replace("'", "''")
    return f"'{s[:200]}'"


def _iso_to_sas_date(value) -> str:
    try:
        d = datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ToolError(f"Invalid date '{value}'; use ISO format YYYY-MM-DD.")
    return '"' + d.strftime("%d%b%Y").upper() + '"d'


def _num(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ToolError(f"Expected a number, got {value!r}.")


def _build_synthetic_sas(table, caslib, server, columns, n_rows, seed=12345):
    """Build a SAS program that synthesises *n_rows* rows from a column spec and
    loads the result into CAS as a promoted (global) table."""
    if not isinstance(columns, list) or not columns:
        raise ToolError("Provide a non-empty list of column specs.")
    for nm in (table, caslib):
        if not _VALID_NAME.match(str(nm or "")):
            raise ToolError(
                f"'{nm}' is not a valid SAS/CAS name (letters, digits, "
                f"underscore; start with a letter/underscore; <=32 chars).")

    n = int(n_rows)
    length_decls, format_decls, body = [], [], []
    uses_p = False
    seen = set()

    for col in columns:
        if not isinstance(col, dict):
            raise ToolError("Each column must be an object with 'name'/'type'.")
        name = str(col.get("name", "")).strip()
        if not _VALID_NAME.match(name):
            raise ToolError(f"Invalid column name '{name}'.")
        if name.lower() in seen:
            raise ToolError(f"Duplicate column name '{name}'.")
        seen.add(name.lower())
        ctype = str(col.get("type", "float")).lower()
        if ctype not in _SYNTH_TYPES:
            raise ToolError(
                f"Column '{name}': type must be one of {', '.join(_SYNTH_TYPES)}.")

        if ctype == "id":
            width = max(6, len(str(max(n, 1))))
            length_decls.append(f"{name} $ {width}")
            body.append(f"{name} = put(_i, z{width}.);")

        elif ctype in ("int", "float"):
            dist = str(col.get("dist", "uniform")).lower()
            mn, mx = _num(col.get("min")), _num(col.get("max"))
            if dist == "normal":
                expr = f"rand('normal', {_num(col.get('mean'), 0.0)}, {_num(col.get('std'), 1.0)})"
            elif dist == "poisson":
                expr = f"rand('poisson', {_num(col.get('lambda'), 1.0)})"
            elif dist == "uniform":
                lo = mn if mn is not None else 0.0
                hi = mx if mx is not None else (1.0 if ctype == "float" else 100.0)
                expr = (f"{lo} + floor(rand('uniform') * ({hi} - {lo} + 1))"
                        if ctype == "int" else
                        f"{lo} + rand('uniform') * ({hi} - {lo})")
            else:
                raise ToolError(
                    f"Column '{name}': dist must be uniform, normal, or poisson.")
            body.append(f"{name} = {expr};")
            if ctype == "int":
                body.append(f"{name} = round({name});")
            elif col.get("decimals") is not None:
                body.append(f"{name} = round({name}, {10 ** (-int(col['decimals'])):.10f});")
            if mn is not None:
                body.append(f"if {name} < {mn} then {name} = {mn};")
            if mx is not None:
                body.append(f"if {name} > {mx} then {name} = {mx};")

        elif ctype == "category":
            levels = col.get("levels")
            if not isinstance(levels, list) or not levels:
                raise ToolError(
                    f"Column '{name}': category requires a non-empty 'levels' list.")
            weights = col.get("weights")
            w = ([max(0.0, _num(x, 0.0)) for x in weights]
                 if weights and len(weights) == len(levels) else [1.0] * len(levels))
            total = sum(w) or 1.0
            length_decls.append(f"{name} $ {min(64, max(len(str(x)) for x in levels))}")
            uses_p = True
            body.append("_p = rand('uniform');")
            cum = 0.0
            for i, lvl in enumerate(levels):
                cum += w[i] / total
                lit = _sas_quote(lvl)
                if i == 0:
                    body.append(f"if _p < {cum:.6f} then {name} = {lit};")
                elif i < len(levels) - 1:
                    body.append(f"else if _p < {cum:.6f} then {name} = {lit};")
                else:
                    body.append(f"else {name} = {lit};")

        elif ctype == "bool":
            body.append(f"{name} = (rand('uniform') < {_num(col.get('p_true'), 0.5)});")

        elif ctype == "date":
            start, end = _iso_to_sas_date(col.get("start")), _iso_to_sas_date(col.get("end"))
            body.append(
                f"{name} = {start} + floor(rand('uniform') * ({end} - {start} + 1));")
            format_decls.append(f"{name} date9.")

    lines = ["data work._mcp_synth;", f"  call streaminit({int(seed)});"]
    if length_decls:
        lines.append("  length " + " ".join(length_decls) + ";")
    if format_decls:
        lines.append("  format " + " ".join(format_decls) + ";")
    lines.append(f"  do _i = 1 to {n};")
    lines += [f"    {s}" for s in body]
    lines += ["    output;", "  end;", f"  drop _i{' _p' if uses_p else ''};", "run;", ""]
    lines += ["cas mcpcas;", "caslib _all_ assign;", "proc casutil;",
              f'  load data=work._mcp_synth outcaslib="{caslib}" casout="{table}" promote;',
              "quit;", "cas mcpcas terminate;"]
    return "\n".join(lines)


async def _resolve_free_table_name(client, server, caslib, base):
    try:
        items, _ = await _get_paged_items(
            f"/casManagement/servers/{server}/caslibs/{caslib}/tables",
            client, limit=1000)
    except Exception:
        return base
    existing = {str(t.get("name", "")).upper() for t in items}
    if base.upper() not in existing:
        return base
    for i in range(1, 1000):
        if f"{base}_{i}".upper() not in existing:
            return f"{base}_{i}"
    return base


# ---------------------------------------------------------------------------
# SAS code execution & structured queries
# ---------------------------------------------------------------------------

@viya.add(
    "execute_sas_code",
    "Execute SAS code in the Viya environment and return the job's log and "
    "listing. Use this for anything beyond a simple query: data preparation, "
    "PROC-based modelling (e.g. PROC LOGISTIC / GRADBOOST / FOREST), assessment, "
    "or any SAS step. For 'show me the top N ...' style questions whose result "
    "you want to chart, prefer query_table — it returns clean rows instead of "
    "log text. Note: each call runs in a fresh compute session that is deleted "
    "afterwards, so WORK tables do not persist between calls; write anything "
    "you need to reuse to a caslib.",
    {"type": "object",
     "properties": {"sas_code": {"type": "string", "description": "The SAS code snippet to execute via the Compute service."}},
     "required": ["sas_code"]},
)
async def execute_sas_code(sas_code: str):
    logger.info("--- TOOL USED: execute_sas_code ---")
    token = await get_token()
    output = await run_one_snippet(sas_code, "1", token)
    if isinstance(output, (list, tuple)) and len(output) >= 4:
        _sid, state, log_text, listing_text = output[:4]
        return {"state": state,
                "log": _truncate_output(log_text),
                "listing": _truncate_output(listing_text)}
    return output


@viya.add(
    "query_table",
    "Run a SQL SELECT against CAS data and return structured rows (columns + "
    "rows). This is the tool to use whenever you want to answer a quantitative "
    "question or feed a chart — e.g. 'the top 10 categories by count'. Unlike "
    "execute_sas_code (which returns SAS log/listing text), this returns clean "
    "JSON rows you can pass straight to render_chart. Reference tables by "
    "their caslib-qualified name, e.g. "
    "select Region, count(*) as n from Public.SUPPLIERS group by Region order by n desc",
    {"type": "object",
     "properties": {
         "sql": {"type": "string", "description": "A single SQL SELECT statement (SAS PROC SQL syntax)."},
         "limit": {"type": "integer", "description": "Maximum rows to return (default 100)."}},
     "required": ["sql"]},
)
async def query_table(sql: str, limit: int = 100):
    logger.info("--- TOOL USED: query_table ---")
    token = await get_token()
    result = await run_query_rows(sql, token, limit=limit)
    if result.get("error"):
        result["log"] = _truncate_output(result.get("log", ""))
    return result


# ---------------------------------------------------------------------------
# Tier 1 — Data Discovery (CAS Management)
# ---------------------------------------------------------------------------

@viya.add(
    "list_cas_servers",
    "List available CAS servers on the Viya environment.",
    {"type": "object", "properties": {}},
)
async def list_cas_servers():
    logger.info("--- TOOL USED: list_cas_servers ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items("/casManagement/servers", client)
        return [{"name": s.get("name"), "id": s.get("id"),
                 "description": s.get("description", "")} for s in items]


@viya.add(
    "list_caslibs",
    "List CAS libraries (caslibs) available on a CAS server.",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string", "description": "CAS server name or ID (e.g. 'cas-shared-default')."},
         "limit": {"type": "integer", "description": "Maximum caslibs to return (default 50)."}},
     "required": ["server_id"]},
)
async def list_caslibs(server_id: str, limit: int = 50):
    logger.info("--- TOOL USED: list_caslibs ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items(
            f"/casManagement/servers/{server_id}/caslibs", client, limit=limit)
        return [{"name": c.get("name"), "type": c.get("type", ""),
                 "description": c.get("description", "")} for c in items]


@viya.add(
    "list_castables",
    "List tables in a CAS library.",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum tables to return (default 50)."}},
     "required": ["server_id", "caslib_name"]},
)
async def list_castables(server_id: str, caslib_name: str, limit: int = 50):
    logger.info("--- TOOL USED: list_castables ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items(
            f"/casManagement/servers/{server_id}/caslibs/{caslib_name}/tables",
            client, limit=limit)
        return [{"name": t.get("name"), "rowCount": t.get("rowCount"),
                 "columnCount": t.get("columnCount")} for t in items]


@viya.add(
    "get_castable_info",
    "Get metadata for a CAS table (row count, column count, size, etc.).",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"}},
     "required": ["server_id", "caslib_name", "table_name"]},
)
async def get_castable_info(server_id: str, caslib_name: str, table_name: str):
    logger.info("--- TOOL USED: get_castable_info ---")
    token = await get_token()
    async with _make_client(token) as client:
        return await _get_json(
            f"/casManagement/servers/{server_id}/caslibs/{caslib_name}/tables/{table_name}",
            client)


@viya.add(
    "get_castable_columns",
    "Get column metadata for a CAS table (names, types, labels, formats).",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum columns to return (default 200)."}},
     "required": ["server_id", "caslib_name", "table_name"]},
)
async def get_castable_columns(server_id: str, caslib_name: str, table_name: str,
                               limit: int = 200):
    logger.info("--- TOOL USED: get_castable_columns ---")
    token = await get_token()
    async with _make_client(token) as client:
        return await fetch_table_columns(client, server_id, caslib_name,
                                         table_name, limit=limit)


@viya.add(
    "get_castable_data",
    "Fetch rows from a CAS table with column names. Good for sampling the "
    "data; for aggregated/filtered results (counts, top N, group-by) use "
    "query_table instead.",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"},
         "limit": {"type": "integer", "description": "Maximum rows (default 100)."},
         "start": {"type": "integer", "description": "Row offset (default 0)."}},
     "required": ["server_id", "caslib_name", "table_name"]},
)
async def get_castable_data(server_id: str, caslib_name: str, table_name: str,
                            limit: int = 100, start: int = 0):
    logger.info("--- TOOL USED: get_castable_data ---")
    token = await get_token()
    from .viya_utils import VIYA_ENDPOINT
    data_source_id = f"cas~fs~{server_id}~fs~{caslib_name}"
    table_id = f"cas~fs~{server_id}~fs~{caslib_name}~fs~{table_name}"
    async with _make_client(token) as client:
        columns = []
        col_start, col_limit = 0, 100
        while True:
            col_resp = await client.get(
                f"{VIYA_ENDPOINT}/dataTables/dataSources/{data_source_id}/tables/{table_name}/columns",
                params={"start": col_start, "limit": col_limit},
                follow_redirects=True)
            col_resp.raise_for_status()
            col_data = col_resp.json()
            for item in col_data.get("items", []):
                columns.append({"name": item.get("name"), "type": item.get("type"),
                                "index": item.get("index")})
            total = col_data.get("count", 0)
            col_start += col_limit
            if col_start >= total:
                break

        row_resp = await client.get(
            f"{VIYA_ENDPOINT}/rowSets/tables/{table_id}/rows",
            params={"start": start, "limit": limit},
            follow_redirects=True)
        row_resp.raise_for_status()
        row_data = row_resp.json()

        col_names = [c["name"] for c in columns]
        rows = [dict(zip(col_names, item.get("cells", [])))
                for item in row_data.get("items", [])]
        return {"columns": col_names, "rows": rows,
                "count": row_data.get("count", len(rows)),
                "start": start, "limit": limit}


# ---------------------------------------------------------------------------
# Tier 2 — Data Operations & Files
# ---------------------------------------------------------------------------

@viya.add(
    "upload_data",
    "Upload CSV data into a CAS table.",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"},
         "csv_data": {"type": "string", "description": "CSV-formatted data string (including header row)."}},
     "required": ["server_id", "caslib_name", "table_name", "csv_data"]},
)
async def upload_data(server_id: str, caslib_name: str, table_name: str, csv_data: str):
    logger.info("--- TOOL USED: upload_data ---")
    token = await get_token()
    from .viya_utils import VIYA_ENDPOINT
    async with _make_client(token) as client:
        resp = await client.post(
            f"{VIYA_ENDPOINT}/casManagement/servers/{server_id}/caslibs/{caslib_name}/tables",
            data={"tableName": table_name, "format": "csv",
                  "containsHeaderRow": "true"},
            files={"file": ("data.csv", csv_data.encode("utf-8"), "text/csv")})
        if resp.status_code == 409:
            return {"status": "table_already_exists", "table_name": table_name,
                    "caslib": caslib_name,
                    "message": f"Table '{table_name}' already exists in caslib "
                               f"'{caslib_name}'. Drop or rename before re-uploading."}
        resp.raise_for_status()
        body = resp.json()
        return {"status": "success", "table_name": body.get("name"),
                "rows_uploaded": body.get("rowCount", 0),
                "column_count": body.get("columnCount", 0),
                "caslib": body.get("caslibName"), "scope": body.get("scope")}


@viya.add(
    "promote_table_to_memory",
    "Promote a CAS table to global scope (makes it visible to all sessions).",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"}},
     "required": ["server_id", "caslib_name", "table_name"]},
)
async def promote_table_to_memory(server_id: str, caslib_name: str, table_name: str):
    logger.info("--- TOOL USED: promote_table_to_memory ---")
    token = await get_token()
    async with _make_client(token) as client:
        try:
            return await _post_json(
                f"/casManagement/servers/{server_id}/caslibs/{caslib_name}/tables/{table_name}",
                client, body={"scope": "global"})
        except _httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                return {"status": "already_promoted",
                        "table": f"{caslib_name}.{table_name}"}
            raise


@viya.add(
    "list_files",
    "List files in the Viya Files Service.",
    {"type": "object",
     "properties": {
         "limit": {"type": "integer", "description": "Maximum files (default 50)."},
         "filter_name": {"type": "string", "description": "Optional name filter (substring match)."}},
     },
)
async def list_files(limit: int = 50, filter_name: Optional[str] = None):
    logger.info("--- TOOL USED: list_files ---")
    token = await get_token()
    filters = f"contains(name,'{filter_name}')" if filter_name else None
    async with _make_client(token) as client:
        items, _ = await _get_paged_items("/files/files", client,
                                          limit=limit, filters=filters)
        return [{"id": f.get("id"), "name": f.get("name"),
                 "contentType": f.get("contentType", ""),
                 "size": f.get("size")} for f in items]


@viya.add(
    "upload_file",
    "Upload a file to the Viya Files Service.",
    {"type": "object",
     "properties": {
         "file_name": {"type": "string"},
         "content": {"type": "string"},
         "content_type": {"type": "string", "description": "MIME type (default 'text/plain')."}},
     "required": ["file_name", "content"]},
)
async def upload_file(file_name: str, content: str, content_type: str = "text/plain"):
    logger.info("--- TOOL USED: upload_file ---")
    token = await get_token()
    from .viya_utils import VIYA_ENDPOINT
    async with _make_client(token) as client:
        resp = await client.post(
            f"{VIYA_ENDPOINT}/files/files",
            content=content.encode("utf-8"),
            headers={"Content-Type": content_type,
                     "Content-Disposition": f'attachment; filename="{file_name}"',
                     "Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


@viya.add(
    "download_file",
    "Download file content from the Viya Files Service.",
    {"type": "object",
     "properties": {"file_id": {"type": "string"}},
     "required": ["file_id"]},
)
async def download_file(file_id: str):
    logger.info("--- TOOL USED: download_file ---")
    token = await get_token()
    from .viya_utils import VIYA_ENDPOINT
    async with _make_client(token) as client:
        resp = await client.get(f"{VIYA_ENDPOINT}/files/files/{file_id}/content")
        resp.raise_for_status()
        return resp.text


# ---------------------------------------------------------------------------
# Data Generation
# ---------------------------------------------------------------------------

@viya.add(
    "generate_synthetic_data",
    "Generate a synthetic CAS table from a column specification. Use this to "
    "create realistic mock data on request (e.g. a procurement dataset for a "
    "demo). Recommended flow: first PROPOSE the column schema to the user in "
    "chat and get their agreement, THEN call this tool. The rows are generated "
    "in SAS and saved to CAS as a promoted (global) table, immediately usable "
    "by the data, charting, AutoML, and scoring tools. Column spec types: "
    "id (sequential identifier); int/float (min, max; or dist 'normal' with "
    "mean/std or 'poisson' with lambda; float also accepts decimals); category "
    "(levels list + optional weights); bool (p_true); date (start/end as "
    "YYYY-MM-DD).",
    {"type": "object",
     "properties": {
         "table_name": {"type": "string"},
         "columns": {"type": "array", "items": {"type": "object"},
                     "description": "Column specs, each with name + type + type-specific options."},
         "n_rows": {"type": "integer", "description": "Rows to generate (default 1000)."},
         "caslib_name": {"type": "string", "description": "Target caslib (default Public)."},
         "server_id": {"type": "string", "description": "CAS server (default cas-shared-default)."},
         "seed": {"type": "integer", "description": "Random seed (default 12345)."}},
     "required": ["table_name", "columns"]},
)
async def generate_synthetic_data(table_name: str, columns: list, n_rows: int = 1000,
                                  caslib_name: str = "Public",
                                  server_id: str = "cas-shared-default",
                                  seed: int = 12345):
    logger.info("--- TOOL USED: generate_synthetic_data ---")
    n = max(1, min(int(n_rows), MAX_SYNTHETIC_ROWS))
    clamped = int(n_rows) > MAX_SYNTHETIC_ROWS
    token = await get_token()
    async with _make_client(token) as client:
        target = await _resolve_free_table_name(client, server_id, caslib_name, table_name)
    code = _build_synthetic_sas(target, caslib_name, server_id, columns, n, seed)
    output = await run_one_snippet(code, "1", token)
    state = output[1] if len(output) > 1 else "unknown"
    log_text = output[2] if len(output) > 2 else ""
    if state not in ("completed", "warning"):
        # The existence check + promote is not atomic — retry once with a
        # unique suffix if a concurrent request claimed the name in between.
        async with _make_client(token) as client:
            now_taken = await _resolve_free_table_name(
                client, server_id, caslib_name, target) != target
        if now_taken:
            target = f"{table_name}_{uuid.uuid4().hex[:6]}"
            code = _build_synthetic_sas(target, caslib_name, server_id, columns, n, seed)
            output = await run_one_snippet(code, "1", token)
            state = output[1] if len(output) > 1 else "unknown"
            log_text = output[2] if len(output) > 2 else ""
    if state not in ("completed", "warning"):
        return {"error": True, "state": state, "log": _truncate_output(log_text),
                "message": (f"Generation of {caslib_name}.{target} failed; "
                            f"check the log and adjust the spec.")}
    result = {
        "table": target, "caslib": caslib_name, "server": server_id,
        "rowCount": n, "promoted": True,
        "columns": [{"name": c.get("name"), "type": c.get("type", "float")}
                    for c in columns if isinstance(c, dict)],
        "message": (f"Created {caslib_name}.{target} with {n} rows. "
                    f"Preview it with get_castable_data."),
    }
    if target != table_name:
        result["renamed_from"] = table_name
        result["note"] = f"'{table_name}' already existed; created '{target}' instead."
    if clamped:
        result["rows_capped"] = MAX_SYNTHETIC_ROWS
    return result


# ---------------------------------------------------------------------------
# Tier 4 — Batch Jobs & Async Execution
# ---------------------------------------------------------------------------

@viya.add(
    "submit_batch_job",
    "Submit a SAS job for asynchronous execution via the Job Execution service.",
    {"type": "object",
     "properties": {
         "sas_code": {"type": "string"},
         "job_name": {"type": "string", "description": "Optional descriptive name."}},
     "required": ["sas_code"]},
)
async def submit_batch_job(sas_code: str, job_name: Optional[str] = None):
    logger.info("--- TOOL USED: submit_batch_job ---")
    token = await get_token()
    from .config import CONTEXT_NAME
    body = {"name": job_name or "copilot-batch-job",
            "jobDefinition": {"type": "Compute", "code": sas_code},
            "arguments": {"_contextName": CONTEXT_NAME}}
    async with _make_client(token) as client:
        return await _post_json("/jobExecution/jobs", client, body=body)


@viya.add(
    "get_job_status",
    "Check the status of a submitted job.",
    {"type": "object", "properties": {"job_id": {"type": "string"}},
     "required": ["job_id"]},
)
async def get_job_status(job_id: str):
    logger.info("--- TOOL USED: get_job_status ---")
    token = await get_token()
    async with _make_client(token) as client:
        return await _get_json(f"/jobExecution/jobs/{job_id}", client)


@viya.add(
    "list_jobs",
    "List recent jobs from the Job Execution service.",
    {"type": "object", "properties": {"limit": {"type": "integer"}}},
)
async def list_jobs(limit: int = 20):
    logger.info("--- TOOL USED: list_jobs ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items("/jobExecution/jobs", client, limit=limit)
        return [{"id": j.get("id"), "name": j.get("name", ""),
                 "state": j.get("state", ""),
                 "creationTimeStamp": j.get("creationTimeStamp", "")} for j in items]


@viya.add(
    "cancel_job",
    "Cancel a running job.",
    {"type": "object", "properties": {"job_id": {"type": "string"}},
     "required": ["job_id"]},
)
async def cancel_job(job_id: str):
    logger.info("--- TOOL USED: cancel_job ---")
    token = await get_token()
    async with _make_client(token) as client:
        await _delete_resource(f"/jobExecution/jobs/{job_id}", client)
        return f"Job {job_id} cancelled."


@viya.add(
    "get_job_log",
    "Retrieve the log of a completed job.",
    {"type": "object", "properties": {"job_id": {"type": "string"}},
     "required": ["job_id"]},
)
async def get_job_log(job_id: str):
    logger.info("--- TOOL USED: get_job_log ---")
    token = await get_token()
    from .viya_utils import VIYA_ENDPOINT
    async with _make_client(token) as client:
        data = await _get_json(f"/jobExecution/jobs/{job_id}", client)
        results = data.get("results", {})
        log_uri = None
        for key, value in results.items():
            if key.endswith(".log.txt"):
                log_uri = value
                break
        if not log_uri:
            for key, value in results.items():
                if key.endswith(".log"):
                    log_uri = value
                    break
        if not log_uri:
            state = data.get("state", "unknown")
            error = data.get("error", {})
            if error:
                return f"Job {state}: {error.get('message', 'No error details')}"
            return f"No log available. Job state: {state}"
        resp = await client.get(f"{VIYA_ENDPOINT}{log_uri}/content")
        resp.raise_for_status()
        return _truncate_output(resp.text)


# ---------------------------------------------------------------------------
# Tier 5 — Model Management & Scoring (AutoML / MLPA, Model Repository, MAS)
# ---------------------------------------------------------------------------

_MLPA_TYPE = "application/vnd.sas.analytics.ml.pipeline.automation.project+json"


@viya.add(
    "list_ml_projects",
    "List AutoML pipeline automation projects.",
    {"type": "object", "properties": {"limit": {"type": "integer"}}},
)
async def list_ml_projects(limit: int = 50):
    logger.info("--- TOOL USED: list_ml_projects ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items(
            "/mlPipelineAutomation/projects", client, limit=limit)
        return [{"id": p.get("id"), "name": p.get("name", ""),
                 "state": p.get("state", ""),
                 "description": p.get("description", "")} for p in items]


@viya.add(
    "create_ml_project",
    "Build a new ML model with AutoML (pipeline automation). SAS auto-detects "
    "the target's measurement level; for classification targets, "
    "target_event_level selects the modeled event level. The data table must "
    "be loaded in CAS. After it finishes, call get_ml_project_results to see "
    "how the model performed. data_table_uri looks like "
    "'/dataTables/dataSources/cas~fs~cas-shared-default~fs~Public/tables/MY_TABLE'.",
    {"type": "object",
     "properties": {
         "project_name": {"type": "string"},
         "data_table_uri": {"type": "string"},
         "target_variable": {"type": "string"},
         "description": {"type": "string"},
         "prediction_type": {"type": "string", "enum": ["binary", "interval", "nominal"],
                             "description": "binary (default), nominal for multiclass, interval for numeric."},
         "target_event_level": {"type": "string", "description": "Event level for a BINARY target only (default '1')."},
         "auto_run": {"type": "boolean", "description": "Automatically run pipelines after creation (default true)."}},
     "required": ["project_name", "data_table_uri", "target_variable"]},
)
async def create_ml_project(project_name: str, data_table_uri: str,
                            target_variable: str, description: str = "",
                            prediction_type: str = "binary",
                            target_event_level: str = "1", auto_run: bool = True):
    logger.info("--- TOOL USED: create_ml_project ---")
    token = await get_token()
    analytics_attrs = {"targetVariable": target_variable, "partitionEnabled": True}
    # targetEventLevel only applies to a BINARY target; sending it for
    # nominal/interval makes MLPA's metadata step reject the parameters.
    if prediction_type == "binary":
        analytics_attrs["targetEventLevel"] = target_event_level
    body = {
        "name": project_name,
        "description": description,
        "type": "predictive",
        "dataTableUri": data_table_uri,
        "pipelineBuildMethod": "automatic",
        "settings": {"autoRun": auto_run, "applyGlobalMetadata": False,
                     "numberOfModels": 5},
        "analyticsProjectAttributes": analytics_attrs,
    }
    async with _make_client(token) as client:
        try:
            return await _post_json("/mlPipelineAutomation/projects", client,
                                    body=body, accept=_MLPA_TYPE)
        except Exception as e:
            # MLPA's metadata step intermittently fails when several projects
            # are created at once under the same identity; retry once with a
            # unique name suffix (also dodges any name/folder collision).
            logger.warning(
                "create_ml_project failed (%s); retrying once with a unique name", e)
            await asyncio.sleep(2)
            body["name"] = f"{project_name}_{uuid.uuid4().hex[:4]}"
            return await _post_json("/mlPipelineAutomation/projects", client,
                                    body=body, accept=_MLPA_TYPE)


@viya.add(
    "run_ml_project",
    "Run (train) an AutoML pipeline automation project.",
    {"type": "object", "properties": {"project_id": {"type": "string"}},
     "required": ["project_id"]},
)
async def run_ml_project(project_id: str):
    logger.info("--- TOOL USED: run_ml_project ---")
    token = await get_token()
    import json as _json
    from .viya_utils import VIYA_ENDPOINT
    async with _make_client(token) as client:
        get_resp = await client.get(
            f"{VIYA_ENDPOINT}/mlPipelineAutomation/projects/{project_id}",
            headers={"Accept": _MLPA_TYPE})
        get_resp.raise_for_status()
        project_body = get_resp.json()
        etag = get_resp.headers.get("etag", "")
        resp = await client.put(
            f"{VIYA_ENDPOINT}/mlPipelineAutomation/projects/{project_id}",
            params={"action": "retrainProject"},
            content=_json.dumps(project_body).encode(),
            headers={"Content-Type": _MLPA_TYPE, "Accept": _MLPA_TYPE,
                     "If-Match": etag, "Accept-Language": "en"})
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"status": "running", "projectId": project_id}
        return resp.json()


@viya.add(
    "get_ml_project_results",
    "Get an AutoML project's results: state, champion model, and the model "
    "leaderboard with fit statistics. Call after run_ml_project (poll until "
    "state is 'completed') to report how well the built model performs.",
    {"type": "object", "properties": {"project_id": {"type": "string"}},
     "required": ["project_id"]},
)
async def get_ml_project_results(project_id: str):
    logger.info("--- TOOL USED: get_ml_project_results ---")
    token = await get_token()
    async with _make_client(token) as client:
        proj = await _get_json(f"/mlPipelineAutomation/projects/{project_id}",
                               client, accept=_MLPA_TYPE)
        results = {"projectId": project_id, "name": proj.get("name", ""),
                   "state": proj.get("state", ""),
                   "championModel": proj.get("championModel")}
        try:
            items, _ = await _get_paged_items(
                f"/mlPipelineAutomation/projects/{project_id}/models",
                client, limit=50)
            results["leaderboard"] = [
                {"name": m.get("name", ""),
                 "algorithm": m.get("algorithmName") or m.get("modelType", ""),
                 "champion": m.get("champion", False),
                 "fitStatistics": (m.get("fitStatistics")
                                   or m.get("assessmentStatistics"))}
                for m in items]
        except Exception as e:
            results["leaderboard"] = []
            results["leaderboardNote"] = f"Leaderboard unavailable: {e}"
        return results


@viya.add(
    "delete_ml_project",
    "Delete an AutoML pipeline automation project (for example, to start over "
    "with a different configuration).",
    {"type": "object", "properties": {"project_id": {"type": "string"}},
     "required": ["project_id"]},
)
async def delete_ml_project(project_id: str):
    logger.info("--- TOOL USED: delete_ml_project ---")
    token = await get_token()
    async with _make_client(token) as client:
        await _delete_resource(f"/mlPipelineAutomation/projects/{project_id}", client)
    return {"status": "deleted", "projectId": project_id}


@viya.add(
    "list_registered_models",
    "List models in the Model Repository.",
    {"type": "object", "properties": {"limit": {"type": "integer"}}},
)
async def list_registered_models(limit: int = 50):
    logger.info("--- TOOL USED: list_registered_models ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items("/modelRepository/models", client,
                                          limit=limit)
        return [{"id": m.get("id"), "name": m.get("name", ""),
                 "description": m.get("description", ""),
                 "modelVersionName": m.get("modelVersionName", "")} for m in items]


@viya.add(
    "list_models_and_decisions",
    "List the ready (published) scoring models and decisions (MAS modules). "
    "These are the modules usable with score_data for real-time scoring.",
    {"type": "object", "properties": {"limit": {"type": "integer"}}},
)
async def list_models_and_decisions(limit: int = 50):
    logger.info("--- TOOL USED: list_models_and_decisions ---")
    token = await get_token()
    async with _make_client(token) as client:
        items, _ = await _get_paged_items("/microanalyticScore/modules", client,
                                          limit=limit)
        return [{"id": m.get("id"), "name": m.get("name", ""),
                 "description": m.get("description", "")} for m in items]


@viya.add(
    "score_data",
    "Score a record against a ready model or decision (MAS module) in real "
    "time. Get the module_id from list_models_and_decisions first.",
    {"type": "object",
     "properties": {
         "module_id": {"type": "string"},
         "input_data": {"type": "object", "description": "Input variable name-value pairs."},
         "step_id": {"type": "string", "description": "Step within the module (default 'score'; some modules use 'execute')."}},
     "required": ["module_id", "input_data"]},
)
async def score_data(module_id: str, input_data: dict, step_id: str = "score"):
    logger.info("--- TOOL USED: score_data ---")
    token = await get_token()
    body = {"inputs": [{"name": k, "value": v} for k, v in input_data.items()]}
    async with _make_client(token) as client:
        return await _post_json(
            f"/microanalyticScore/modules/{module_id}/steps/{step_id}", client,
            body=body)


# ---------------------------------------------------------------------------
# Tier 6 — Data Insights
# ---------------------------------------------------------------------------

@viya.add(
    "explain_data",
    "Explain a column of a CAS table in relation to the other columns (SAS "
    "Insights). Returns natural-language descriptions of the variable, its "
    "outliers, and variable-screening results — useful for understanding "
    "which variables drive a target before exploring or modelling the data.",
    {"type": "object",
     "properties": {
         "server_id": {"type": "string"},
         "caslib_name": {"type": "string"},
         "table_name": {"type": "string"},
         "target_variable": {"type": "string"},
         "date_variable": {"type": "string", "description": "Optional time-series column; enables forecast insights."}},
     "required": ["server_id", "caslib_name", "table_name", "target_variable"]},
)
async def explain_data(server_id: str, caslib_name: str, table_name: str,
                       target_variable: str, date_variable: Optional[str] = None):
    logger.info("--- TOOL USED: explain_data ---")
    token = await get_token()
    body = {"cas": {"server": server_id, "library": caslib_name, "table": table_name},
            "targetVariable": target_variable,
            "includeVariableDescription": True,
            "includeOutlierDescription": True}
    if date_variable:
        body["dateVariable"] = date_variable
    async with _make_client(token) as client:
        return await _post_json("/insights/explain", client, body=body)
