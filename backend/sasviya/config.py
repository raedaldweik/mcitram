# Vendored from sas-mcp-server (Copyright © 2025, SAS Institute Inc.,
# Apache-2.0), adapted: reading the env is tolerant — the app boots without a
# Viya connection and the tools report a clear "not configured" error instead.

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sasviya")

SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() not in ("false", "0", "no")

VIYA_ENDPOINT = os.getenv("VIYA_ENDPOINT", "").rstrip("/")
CLIENT_ID = os.getenv("CLIENT_ID", "sas-mcp")
# Optional OAuth client secret. Leave empty for a public client (PKCE /
# allowpublic); set it only when the client is registered as confidential.
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
CONTEXT_NAME = os.getenv("COMPUTE_CONTEXT_NAME", "SAS Job Execution compute context")
# Cap the size (characters) of each execute_sas_code log/listing field so a
# verbose PROC cannot overflow the agent's context window. 0 disables capping.
MAX_SAS_OUTPUT_CHARS = int(os.getenv("MAX_SAS_OUTPUT_CHARS", "12000"))

VIYA_USERNAME = os.getenv("VIYA_USERNAME", "")
VIYA_PASSWORD = os.getenv("VIYA_PASSWORD", "")
VIYA_REFRESH_TOKEN = os.getenv("VIYA_REFRESH_TOKEN", "")


def configured() -> bool:
    return bool(VIYA_ENDPOINT) and bool(
        VIYA_REFRESH_TOKEN or (VIYA_USERNAME and VIYA_PASSWORD))
