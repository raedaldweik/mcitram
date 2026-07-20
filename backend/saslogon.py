"""SAS Logon (Viya OAuth) token management.

Adapted from the sas-mcp-server headless auth path (auth.py + stdio_server.py,
Copyright © 2025, SAS Institute Inc. — Apache-2.0): the same grant-selection
rules, made async and instantiable so the app can hold one authenticated
session per SAS environment (the Viya analytics environment and the Visual
Investigator environment are configured independently).

Grant preference (identical to the MCP servers):
1. ``refresh_token`` — works for any identity, including SSO/federated (Okta)
   users. Obtain one interactively once (see sas-mcp-server
   examples/get_refresh_token.py).
2. ``password`` — only for identities SAS Logon can authenticate directly
   (e.g. LDAP-backed users).
"""
from __future__ import annotations

import asyncio
import time

import httpx

# Refresh the cached token this many seconds before it actually expires.
_TOKEN_EXPIRY_MARGIN = 60.0


def select_grant(refresh_token: str = "", username: str = "",
                 password: str = "") -> dict | None:
    if refresh_token:
        return {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if username and password:
        return {"grant_type": "password", "username": username, "password": password}
    return None


def client_request(grant_data: dict, client_id: str,
                   client_secret: str = "") -> tuple[dict, tuple | None]:
    """Public clients send client_id in the body with no Basic auth header;
    confidential clients authenticate with HTTP Basic auth."""
    data = {**grant_data, "client_id": client_id}
    auth = (client_id, client_secret) if client_secret else None
    return data, auth


class AuthenticationError(RuntimeError):
    pass


class SASLogonAuth:
    """Cached, lock-protected access-token provider for one SAS environment."""

    def __init__(self, endpoint: str, client_id: str = "sas-mcp",
                 client_secret: str = "", refresh_token: str = "",
                 username: str = "", password: str = "", verify: bool = True,
                 label: str = "SAS Viya"):
        self.endpoint = (endpoint or "").rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.verify = verify
        self.label = label
        self._lock = asyncio.Lock()
        # refresh_token is seeded from config and updated if SAS Logon rotates it
        self._cache = {"token": "", "expires_at": 0.0, "refresh_token": refresh_token}

    @property
    def configured(self) -> bool:
        return bool(self.endpoint) and (
            bool(self._cache["refresh_token"]) or bool(self.username and self.password))

    async def get_token(self) -> str:
        if self._cache["token"] and time.monotonic() < self._cache["expires_at"]:
            return self._cache["token"]
        async with self._lock:
            # Re-check inside the lock — another coroutine may have refreshed.
            if self._cache["token"] and time.monotonic() < self._cache["expires_at"]:
                return self._cache["token"]
            if not self.endpoint:
                raise AuthenticationError(
                    f"{self.label} is not configured (no endpoint set). "
                    f"Set the environment variables and redeploy.")
            grant = select_grant(
                refresh_token=self._cache["refresh_token"],
                username=self.username, password=self.password)
            if grant is None:
                raise AuthenticationError(
                    f"No {self.label} credentials configured. Set a refresh "
                    f"token (required for SSO/federated identities) or a "
                    f"username and password.")
            data, auth = client_request(grant, self.client_id, self.client_secret)
            async with httpx.AsyncClient(verify=self.verify, timeout=60.0) as client:
                resp = await client.post(
                    f"{self.endpoint}/SASLogon/oauth/token",
                    auth=auth,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=data,
                )
                # Public clients differ by deployment: some SAS Logon setups
                # want client_id in the body with no Basic header (sas-mcp
                # style), others (e.g. sas.cli on RACE images) expect the
                # empty-secret Basic form. Try the other shape once on 401.
                if resp.status_code == 401 and not self.client_secret:
                    resp = await client.post(
                        f"{self.endpoint}/SASLogon/oauth/token",
                        auth=(self.client_id, ""),
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data=grant,
                    )
            if resp.status_code >= 400:
                raise AuthenticationError(
                    f"{self.label} sign-in failed ({resp.status_code}): "
                    f"{resp.text[:300]}")
            body = resp.json()
            self._cache["token"] = body["access_token"]
            expires_in = float(body.get("expires_in", 0))
            self._cache["expires_at"] = time.monotonic() + max(
                expires_in - _TOKEN_EXPIRY_MARGIN, 0.0)
            if body.get("refresh_token"):
                self._cache["refresh_token"] = body["refresh_token"]
            return self._cache["token"]
