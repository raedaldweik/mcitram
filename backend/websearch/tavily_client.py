"""Thin async wrapper around the Tavily API.

Vendored from the Web_Search news MCP server.

Only the two endpoints we need are implemented: ``/search`` (web and news
search, with optional domain include/exclude) and ``/extract`` (fetch the
cleaned full text of one or more URLs). Domain enforcement is applied here so
every tool path goes through the same allow/deny logic.
"""

from typing import Any, Optional

import httpx

from .config import (
    APPROVED_DOMAINS,
    BLOCKED_DOMAINS,
    REQUEST_TIMEOUT,
    SSL_VERIFY,
    TAVILY_API_KEY,
    TAVILY_BASE_URL,
    logger,
)


class TavilyError(RuntimeError):
    """Raised when the Tavily API returns an error or is misconfigured."""


def _host_of(url: str) -> str:
    """Return the bare lowercase host of a URL (no scheme, no path, no www.)."""
    host = (url or "").strip().lower().split("://", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def domain_allowed(url: str) -> bool:
    """Whether *url*'s host passes the approved/blocked domain policy.

    A host matches a configured domain if it equals it or is a sub-domain of it
    (so ``traffic.gov.ae`` matches an approved ``gov.ae``).
    """
    host = _host_of(url)
    if not host:
        return False

    def _matches(host: str, domains: list[str]) -> bool:
        return any(host == d or host.endswith("." + d) for d in domains)

    if BLOCKED_DOMAINS and _matches(host, BLOCKED_DOMAINS):
        return False
    if APPROVED_DOMAINS and not _matches(host, APPROVED_DOMAINS):
        return False
    return True


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not TAVILY_API_KEY:
        raise TavilyError(
            "TAVILY_API_KEY is not set. Get a free key at https://tavily.com "
            "and set it in the environment."
        )
    url = f"{TAVILY_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise TavilyError(f"Could not reach Tavily ({path}): {e}") from e
    if resp.status_code == 401:
        raise TavilyError("Tavily rejected the API key (401). Check TAVILY_API_KEY.")
    if resp.status_code == 429:
        raise TavilyError("Tavily rate limit / quota exceeded (429). Try again later.")
    if resp.status_code >= 400:
        # Surface Tavily's own message when present; it is usually actionable.
        detail = resp.text[:500]
        raise TavilyError(f"Tavily error {resp.status_code} on {path}: {detail}")
    return resp.json()


async def search(
    query: str,
    *,
    topic: str = "general",
    max_results: int = 8,
    search_depth: str = "basic",
    time_range: Optional[str] = None,
    days: Optional[int] = None,
    include_answer: bool = False,
    include_domains: Optional[list[str]] = None,
    exclude_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Call Tavily ``/search``, layering in the configured domain policy.

    Approved domains are intersected with any per-call ``include_domains`` and
    blocked domains are added to ``exclude_domains`` so the policy can never be
    widened by a tool argument.
    """
    payload: dict[str, Any] = {
        "query": query,
        "topic": topic,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
    }
    if time_range:
        payload["time_range"] = time_range
    if days is not None:
        payload["days"] = days

    # Domain policy: approved list narrows (intersection), blocked list widens
    # the exclusions. A tool argument can only narrow, never broaden. A caller
    # may narrow to a sub-domain of an approved domain (e.g. include
    # "traffic.gov.ae" when "gov.ae" is approved); anything not under an
    # approved domain is dropped, falling back to the full approved list.
    inc = [_host_of(d) for d in (include_domains or [])]
    if APPROVED_DOMAINS:
        inc = [d for d in inc
               if any(d == a or d.endswith("." + a) for a in APPROVED_DOMAINS)
               ] or list(APPROVED_DOMAINS)
    if inc:
        payload["include_domains"] = list(dict.fromkeys(inc))

    exc = list(exclude_domains or []) + list(BLOCKED_DOMAINS)
    if exc:
        payload["exclude_domains"] = list(dict.fromkeys(exc))

    logger.info(
        "Tavily search: topic=%s depth=%s results=%s range=%s include=%s exclude=%s",
        topic, search_depth, max_results, time_range or days,
        payload.get("include_domains"), payload.get("exclude_domains"),
    )
    return await _post("/search", payload)


async def extract(urls: list[str], *, extract_depth: str = "basic") -> dict[str, Any]:
    """Call Tavily ``/extract`` to fetch cleaned full text for *urls*."""
    payload = {"urls": urls, "extract_depth": extract_depth}
    logger.info("Tavily extract: %d url(s)", len(urls))
    return await _post("/extract", payload)
