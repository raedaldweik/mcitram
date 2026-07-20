# Vendored from the Web_Search news MCP server, adapted from FastMCP
# registration to the in-process ToolSet used by this app's agents. Tool
# names, arguments, and behavior match the MCP server.

"""Web intelligence tools (Tavily): news search, web search, multi-angle
topic monitoring, and full-article reading — plus a SAS-documentation-scoped
variant used by the SAS Copilot's platform-guide specialist."""

from __future__ import annotations

from typing import Optional

from toolset import ToolSet
from .config import (
    APPROVED_DOMAINS,
    BLOCKED_DOMAINS,
    DEFAULT_SEARCH_DEPTH,
    DEFAULT_TIME_RANGE,
    DOMAIN_ENFORCE,
    MAX_CONTENT_CHARS,
    MAX_RESULTS,
    SAS_DOCS_DOMAINS,
    VALID_SEARCH_DEPTHS,
    VALID_TIME_RANGES,
    logger,
)
from .tavily_client import TavilyError, domain_allowed, extract, search


def _host(url: str) -> str:
    host = (url or "").strip().lower().split("://", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _truncate(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if not text or limit <= 0 or len(text) <= limit:
        return text or ""
    return (
        f"{text[:limit]}\n\n...[truncated {len(text) - limit} characters — "
        f"read_article on a narrower section or ask a more specific question "
        f"for the rest]...")


def _shape_results(results: list[dict]) -> list[dict]:
    shaped = []
    for r in results or []:
        shaped.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": _host(r.get("url", "")),
            "published_date": r.get("published_date"),
            "snippet": _truncate(r.get("content", ""), 600),
            "relevance": round(r.get("score", 0.0), 3) if r.get("score") else None,
        })
    return shaped


def _normalise_depth(value: Optional[str]) -> str:
    v = (value or DEFAULT_SEARCH_DEPTH).lower()
    return v if v in VALID_SEARCH_DEPTHS else "basic"


def _normalise_range(value: Optional[str]) -> Optional[str]:
    if value is None:
        return DEFAULT_TIME_RANGE if DEFAULT_TIME_RANGE in VALID_TIME_RANGES else "week"
    v = value.lower()
    if v in ("", "all", "any", "none"):
        return None
    return v if v in VALID_TIME_RANGES else "week"


web = ToolSet("web_intelligence")


@web.add(
    "get_intelligence_scope",
    "Return this assistant's news/intelligence scope and search defaults: "
    "whether searches are restricted to approved domains, which domains are "
    "blocked, and the default recency window. Call this first in a new "
    "conversation.",
    {"type": "object", "properties": {}},
)
async def get_intelligence_scope():
    logger.info("--- TOOL USED: get_intelligence_scope ---")
    return {
        "approved_domains": APPROVED_DOMAINS,
        "blocked_domains": BLOCKED_DOMAINS,
        "domain_allow_list_active": bool(APPROVED_DOMAINS),
        "reading_outside_approved_blocked": bool(APPROVED_DOMAINS and DOMAIN_ENFORCE),
        "default_time_range": DEFAULT_TIME_RANGE,
        "default_max_results": MAX_RESULTS,
        "notes": ("Searches are limited to approved_domains when that list is "
                  "non-empty. When it is empty, the open web is searched "
                  "except for blocked_domains."),
    }


@web.add(
    "search_news",
    "Search recent NEWS for a topic and return ranked articles. Use this for "
    "current events, announcements, regulations, and emerging trends. "
    "time_range is one of day | week | month | year; pass an empty string to "
    "drop the recency filter. Returns articles with title, source, "
    "published_date, a short snippet, and the url (pass a url to read_article "
    "for the full text).",
    {"type": "object",
     "properties": {
         "query": {"type": "string"},
         "time_range": {"type": "string", "description": "day | week | month | year | '' (any)."},
         "max_results": {"type": "integer"},
         "search_depth": {"type": "string", "enum": ["basic", "advanced"]}},
     "required": ["query"]},
)
async def search_news(query: str, time_range: Optional[str] = None,
                      max_results: Optional[int] = None,
                      search_depth: Optional[str] = None):
    logger.info("--- TOOL USED: search_news (%s) ---", query)
    try:
        data = await search(
            query, topic="news", max_results=max_results or MAX_RESULTS,
            search_depth=_normalise_depth(search_depth),
            time_range=_normalise_range(time_range), include_answer=False)
    except TavilyError as e:
        return {"error": str(e), "query": query, "articles": []}
    return {"query": query,
            "time_range": _normalise_range(time_range) or "any",
            "articles": _shape_results(data.get("results", []))}


@web.add(
    "search_web",
    "Search the wider WEB for background and context (not just news). Use for "
    "definitions, reference material, organisation background, or anything "
    "that is not strictly recent news. Returns a short synthesized answer "
    "plus supporting sources.",
    {"type": "object",
     "properties": {
         "query": {"type": "string"},
         "max_results": {"type": "integer"},
         "search_depth": {"type": "string", "enum": ["basic", "advanced"]}},
     "required": ["query"]},
)
async def search_web(query: str, max_results: Optional[int] = None,
                     search_depth: Optional[str] = None):
    logger.info("--- TOOL USED: search_web (%s) ---", query)
    try:
        data = await search(
            query, topic="general", max_results=max_results or MAX_RESULTS,
            search_depth=_normalise_depth(search_depth), time_range=None,
            include_answer=True)
    except TavilyError as e:
        return {"error": str(e), "query": query, "sources": []}
    return {"query": query, "answer": data.get("answer"),
            "sources": _shape_results(data.get("results", []))}


@web.add(
    "monitor_topic",
    "Build a multi-angle news digest for a topic — good for monitoring. Runs "
    "one news search per angle (e.g. ['regulation', 'technology', 'fraud "
    "detection']) and merges the results into a single de-duplicated digest, "
    "newest first. Use this to scan an area of interest in one call rather "
    "than many.",
    {"type": "object",
     "properties": {
         "topic": {"type": "string"},
         "angles": {"type": "array", "items": {"type": "string"}},
         "time_range": {"type": "string"},
         "per_angle": {"type": "integer", "description": "Articles per angle (default 4)."}},
     "required": ["topic"]},
)
async def monitor_topic(topic: str, angles: Optional[list] = None,
                        time_range: Optional[str] = None, per_angle: int = 4):
    logger.info("--- TOOL USED: monitor_topic (%s) ---", topic)
    rng = _normalise_range(time_range)
    queries = [f"{topic} {a}".strip() for a in (angles or [""])]
    seen: set[str] = set()
    digest: list[dict] = []
    errors: list[str] = []
    for q in queries:
        try:
            data = await search(q, topic="news", max_results=per_angle,
                                search_depth=_normalise_depth(None), time_range=rng)
        except TavilyError as e:
            errors.append(f"{q}: {e}")
            continue
        for art in _shape_results(data.get("results", [])):
            key = art["url"]
            if key and key not in seen:
                seen.add(key)
                art["matched_angle"] = q
                digest.append(art)
    digest.sort(key=lambda a: a.get("published_date") or "", reverse=True)
    result = {"topic": topic, "time_range": rng or "any",
              "article_count": len(digest), "articles": digest}
    if errors:
        result["errors"] = errors
    return result


@web.add(
    "read_article",
    "Fetch the cleaned full text of a single article/page by URL. Use this "
    "after a search to read a promising result in depth. Long pages are "
    "truncated to keep the response within the model's context window.",
    {"type": "object", "properties": {"url": {"type": "string"}},
     "required": ["url"]},
)
async def read_article(url: str):
    logger.info("--- TOOL USED: read_article (%s) ---", url)
    if not url or "://" not in url:
        return {"error": "Provide a full URL including http(s)://", "url": url}
    if DOMAIN_ENFORCE and not domain_allowed(url):
        allowed = ", ".join(APPROVED_DOMAINS) if APPROVED_DOMAINS else "(none)"
        return {"error": (f"{_host(url)} is outside this assistant's approved "
                          f"domains and cannot be read. Approved domains: {allowed}."),
                "url": url}
    try:
        data = await extract([url])
    except TavilyError as e:
        return {"error": str(e), "url": url}
    results = data.get("results") or []
    if not results:
        failed = data.get("failed_results") or []
        reason = failed[0].get("error") if failed else "no content returned"
        return {"error": f"Could not extract article: {reason}", "url": url}
    first = results[0]
    return {"url": url, "source": _host(url),
            "content": _truncate(first.get("raw_content") or first.get("content", ""))}


# ---------------------------------------------------------------------------
# SAS documentation lookup — a retrieval layer over the official SAS docs
# sites, used by the SAS Copilot's platform-guide specialist. Same Tavily
# backend, hard-scoped to the SAS_DOCS_DOMAINS list.
# ---------------------------------------------------------------------------

sasdocs = ToolSet("sas_docs")


@sasdocs.add(
    "search_sas_documentation",
    "Search the official SAS documentation and community sites "
    "(documentation.sas.com, developer.sas.com, support.sas.com, "
    "communities.sas.com, blogs.sas.com) for how-to guidance, REST API "
    "references, PROC syntax, and platform administration answers. Returns a "
    "synthesized answer plus source pages — read a page in full with "
    "read_sas_documentation when the snippet isn't enough.",
    {"type": "object",
     "properties": {
         "query": {"type": "string"},
         "max_results": {"type": "integer"}},
     "required": ["query"]},
)
async def search_sas_documentation(query: str, max_results: Optional[int] = None):
    logger.info("--- TOOL USED: search_sas_documentation (%s) ---", query)
    try:
        data = await search(
            query, topic="general", max_results=max_results or MAX_RESULTS,
            search_depth="advanced", time_range=None, include_answer=True,
            include_domains=list(SAS_DOCS_DOMAINS))
    except TavilyError as e:
        return {"error": str(e), "query": query, "sources": []}
    return {"query": query, "answer": data.get("answer"),
            "sources": _shape_results(data.get("results", []))}


@sasdocs.add(
    "read_sas_documentation",
    "Fetch the cleaned full text of one SAS documentation/community page by "
    "URL (must be on an official SAS domain).",
    {"type": "object", "properties": {"url": {"type": "string"}},
     "required": ["url"]},
)
async def read_sas_documentation(url: str):
    logger.info("--- TOOL USED: read_sas_documentation (%s) ---", url)
    host = _host(url)
    if not any(host == d or host.endswith("." + d) for d in SAS_DOCS_DOMAINS):
        return {"error": (f"{host} is not a SAS documentation domain. Allowed: "
                          f"{', '.join(SAS_DOCS_DOMAINS)}."), "url": url}
    try:
        data = await extract([url])
    except TavilyError as e:
        return {"error": str(e), "url": url}
    results = data.get("results") or []
    if not results:
        return {"error": "Could not extract the page.", "url": url}
    first = results[0]
    return {"url": url, "source": host,
            "content": _truncate(first.get("raw_content") or first.get("content", ""))}
