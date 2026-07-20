# Vendored from the Web_Search news MCP server, adapted: plain logging and
# tolerant configuration (the app boots without a Tavily key; the tools then
# return a clear error the agent can relay).

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("websearch")


def _parse_domains(raw: str) -> list[str]:
    out = []
    for chunk in (raw or "").replace("\n", ",").split(","):
        item = chunk.strip().lower()
        if item:
            item = item.split("://", 1)[-1].split("/", 1)[0]
            if item.startswith("www."):
                item = item[4:]
            out.append(item)
    return out


TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
TAVILY_BASE_URL = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("TAVILY_TIMEOUT", "60"))
SSL_VERIFY = os.getenv("TAVILY_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

# Optional domain policy for the general web/news tools. Empty = open web.
APPROVED_DOMAINS = _parse_domains(os.getenv("APPROVED_DOMAINS", ""))
BLOCKED_DOMAINS = _parse_domains(os.getenv("BLOCKED_DOMAINS", ""))
DOMAIN_ENFORCE = os.getenv("DOMAIN_ENFORCE", "true").lower() not in ("false", "0", "no")

MAX_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "8"))
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "14000"))
DEFAULT_SEARCH_DEPTH = os.getenv("DEFAULT_SEARCH_DEPTH", "basic").lower()
DEFAULT_TIME_RANGE = os.getenv("DEFAULT_TIME_RANGE", "month").lower()

VALID_SEARCH_DEPTHS = ("basic", "advanced")
VALID_TIME_RANGES = ("day", "week", "month", "year")

# Domains the SAS platform-guide specialist searches for authoritative answers.
SAS_DOCS_DOMAINS = _parse_domains(os.getenv(
    "SAS_DOCS_DOMAINS",
    "documentation.sas.com, go.documentation.sas.com, developer.sas.com, "
    "support.sas.com, communities.sas.com, blogs.sas.com, video.sas.com, sas.com"))


def configured() -> bool:
    return bool(TAVILY_API_KEY)
