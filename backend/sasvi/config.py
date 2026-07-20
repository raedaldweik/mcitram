"""Configuration for the SAS Visual Investigator toolset.

The VI environment is configured independently of the Viya analytics
environment (they are different deployments), using VI_* variables with the
same conventions as the sas-mcp-server family.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sasvi")

VI_ENDPOINT = os.getenv("VI_ENDPOINT", "").rstrip("/")
VI_CLIENT_ID = os.getenv("VI_CLIENT_ID", "sas-mcp")
VI_CLIENT_SECRET = os.getenv("VI_CLIENT_SECRET", "")
VI_REFRESH_TOKEN = os.getenv("VI_REFRESH_TOKEN", "")
VI_USERNAME = os.getenv("VI_USERNAME", "")
VI_PASSWORD = os.getenv("VI_PASSWORD", "")
VI_SSL_VERIFY = os.getenv("VI_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

# Optional free-text description of what is deployed on this VI environment,
# surfaced to the agent via get_investigation_scope.
VI_USE_CASE = os.getenv(
    "VI_USE_CASE",
    "Procurement integrity monitoring: alerts on suppliers, tenders and "
    "payments flagged by detection scenarios, with entity networks for "
    "investigation.")


def configured() -> bool:
    return bool(VI_ENDPOINT) and bool(
        VI_REFRESH_TOKEN or (VI_USERNAME and VI_PASSWORD))
