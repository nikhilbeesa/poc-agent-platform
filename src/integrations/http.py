"""HTTP for the Jira / Azure DevOps connectors: URL safety, retries, and error messages that never contain a secret."""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from urllib.parse import urlparse

import requests


class IntegrationError(Exception):
    def __init__(self, message: str, status: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.status, self.details = status, details or {}


def _allow_local() -> bool:
    return os.environ.get("INTEGRATIONS_ALLOW_LOCAL") == "1"   # tests / on-prem demos only


def validate_url(url: str, default_suffixes: tuple[str, ...], env_var: str) -> str:
    """The server calls whatever address the user typed, so it must be a real https tool host — never an internal
    address (SSRF). Allowed hosts: the vendor's cloud domains plus an optional comma-separated allow-list in env_var
    (for Jira Data Center / Azure DevOps Server)."""
    p = urlparse((url or "").strip())
    host = (p.hostname or "").lower()
    if not host:
        raise IntegrationError("Enter the full address, e.g. https://your-company.atlassian.net")
    local_ok = _allow_local() and host in ("localhost", "127.0.0.1")
    if p.scheme != "https" and not local_ok:
        raise IntegrationError("The address must start with https://")
    allowed = default_suffixes + tuple(x.strip().lower() for x in os.environ.get(env_var, "").split(",") if x.strip())
    if not local_ok and not any(host == a.lstrip(".") or (a.startswith(".") and host.endswith(a)) for a in allowed):
        raise IntegrationError(f"“{host}” is not an allowed host. Allowed: {', '.join(allowed)}. "
                               f"An administrator can add self-hosted servers with the {env_var} setting.")
    if not local_ok:
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise IntegrationError("That address resolves to a private network and cannot be used.")
        except socket.gaierror:
            raise IntegrationError(f"Could not find “{host}” — check the address.")
    return f"{p.scheme}://{p.netloc}"


def call(method: str, url: str, *, auth: tuple[str, str], json=None, headers: dict | None = None,
         secrets: tuple[str, ...] = (), retries: int = 3) -> tuple[int, dict | list | None]:
    """One API call with retry on 429 / 5xx (honouring Retry-After). Returns (status, parsed body). Raises
    IntegrationError for any 4xx/5xx that is left, with the vendor's own message and secrets removed."""
    hdrs = {"Accept": "application/json", **(headers or {})}
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, auth=auth, json=json, headers=hdrs, timeout=30, allow_redirects=False)
        except requests.RequestException as e:
            last = IntegrationError(_redact(f"Could not reach the server: {type(e).__name__}", secrets))
            time.sleep(min(2 ** attempt, 8))
            continue
        if r.status_code in (429, 502, 503, 504) and attempt < retries:
            time.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), 20))
            continue
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = None
        if 300 <= r.status_code < 400:
            raise IntegrationError("The server redirected the request (check the address / sign-in).", r.status_code)
        if r.status_code == 401:
            raise IntegrationError("Sign-in was rejected — check the email/token (or personal access token).", 401)
        if r.status_code == 403:
            raise IntegrationError("Access denied — the account lacks permission for this project.", 403, {"body": body})
        if r.status_code >= 400:
            raise IntegrationError(_redact(_vendor_message(body) or f"HTTP {r.status_code}", secrets), r.status_code, {"body": body})
        return r.status_code, body
    raise last or IntegrationError("The request failed.")


def _vendor_message(body) -> str:
    if isinstance(body, dict):
        parts = [str(m) for m in (body.get("errorMessages") or [])] + [f"{k}: {v}" for k, v in (body.get("errors") or {}).items()]
        return "; ".join(parts) or str(body.get("message") or "")[:300]
    return ""


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "•••")
    return text
