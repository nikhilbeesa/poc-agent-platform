"""
Token vault — lets a person save a Jira API token / Azure DevOps PAT for a project without it ever being stored in
a readable form.

  * Each project has ONE password chosen by the person. The password is never stored or logged.
  * The key is derived from it with scrypt (slow on purpose, so a stolen copy of the data resists guessing) and every
    token is sealed with AES-256-GCM. GCM also detects tampering, so a wrong password simply fails to open.
  * Each sealed token is bound to its project and target (associated data), so it cannot be moved elsewhere.
  * Opening the vault gives a short-lived, in-memory ticket; the browser only ever holds that ticket, never the token.
  * Repeated wrong passwords lock the vault for a while (online guessing).

The vault dict is plain JSON (safe to persist); it must still never be sent to the browser — the server strips it.
"""

from __future__ import annotations

import base64
import os
import secrets
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MIN_PASSWORD = 10
TICKET_TTL = 15 * 60
KDF = {"n": 2 ** 15, "r": 8, "p": 1}
_CHECK = b"backlog-vault-ok"


class VaultError(Exception):
    def __init__(self, message: str, status: int = 400, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


def _b(x: bytes) -> str:
    return base64.b64encode(x).decode()


def _u(s: str) -> bytes:
    return base64.b64decode(s)


def _derive(password: str, salt: bytes, kdf: dict) -> bytes:
    return Scrypt(salt=salt, length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(password.encode())


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> dict:
    nonce = os.urandom(12)
    return {"n": _b(nonce), "ct": _b(AESGCM(key).encrypt(nonce, plaintext, aad))}


def _open(key: bytes, blob: dict, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(_u(blob["n"]), _u(blob["ct"]), aad)


def check_password_strength(password: str, secrets_to_avoid: tuple[str, ...] = ()) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise VaultError(f"Choose a password of at least {MIN_PASSWORD} characters.")
    if len(set(password)) < 4:
        raise VaultError("That password is too repetitive — mix in different characters.")
    low = password.lower()
    for s in secrets_to_avoid:
        if len(s or "") >= 6 and (s.lower() in low or low in s.lower()):     # short strings match by accident
            raise VaultError("Don't reuse your token or email as the password.")


# ---- throttling of wrong passwords (in memory; resets on restart) ---------------------------
_FAILS: dict[str, tuple[int, float]] = {}


def _throttle(project_id: str) -> None:
    n, until = _FAILS.get(project_id, (0, 0.0))
    if until > time.time():
        raise VaultError("Too many wrong passwords. Try again shortly.", 429, int(until - time.time()) + 1)


def _failed(project_id: str) -> None:
    n, _ = _FAILS.get(project_id, (0, 0.0))
    n += 1
    _FAILS[project_id] = (n, time.time() + (min(30 * 2 ** (n - 5), 900) if n >= 5 else 0))


def _aad(project_id: str, target: str) -> bytes:
    return f"{project_id}|{target}".encode()


def _key_for(vault: dict, project_id: str, password: str) -> bytes:
    _throttle(project_id)
    key = _derive(password or "", _u(vault["kdf"]["salt"]), vault["kdf"])
    try:
        if _open(key, vault["check"], _aad(project_id, "check")) != _CHECK:
            raise InvalidTag()
    except InvalidTag:
        _failed(project_id)
        left = max(0, 5 - _FAILS.get(project_id, (0, 0))[0])
        raise VaultError("Wrong password." + (f" {left} attempt(s) left before a short lock." if left else ""), 401)
    _FAILS.pop(project_id, None)
    return key


# ---- public API -------------------------------------------------------------------------------
def targets(vault: dict | None) -> list[str]:
    return sorted((vault or {}).get("entries", {}))


def save_token(vault: dict | None, project_id: str, password: str, target: str, token: str) -> dict:
    """Adds/replaces one token. Creates the vault (choosing the password) if there is none, otherwise the password must
    be the project's existing one."""
    if not token:
        raise VaultError("There is no token to save.")
    if not vault or not vault.get("entries"):
        check_password_strength(password, (token,))
        salt = os.urandom(16)
        key = _derive(password, salt, KDF)
        vault = {"v": 1, "kdf": {**KDF, "salt": _b(salt)}, "check": _seal(key, _CHECK, _aad(project_id, "check")), "entries": {}}
    else:
        key = _key_for(vault, project_id, password)
    vault["entries"][target] = _seal(key, token.encode(), _aad(project_id, target))
    return vault


def unlock(vault: dict | None, project_id: str, password: str) -> dict[str, str]:
    """{target: token} for every saved token — held only in memory by the caller, never persisted or returned."""
    if not vault or not vault.get("entries"):
        raise VaultError("There are no saved tokens for this project.", 404)
    key = _key_for(vault, project_id, password)
    try:
        return {t: _open(key, blob, _aad(project_id, t)).decode() for t, blob in vault["entries"].items()}
    except InvalidTag:
        raise VaultError("The saved data could not be opened.", 500)


def forget(vault: dict | None, target: str | None) -> dict | None:
    """Remove one token, or (target=None) the whole vault. When the last token goes the vault goes too, so a new
    password can be chosen next time."""
    if not vault or target is None:
        return None
    vault["entries"].pop(target, None)
    return vault if vault["entries"] else None


# ---- unlock tickets -----------------------------------------------------------------------------
_TICKETS: dict[str, dict] = {}


def issue_ticket(project_id: str, tokens: dict[str, str]) -> str:
    now = time.time()
    for k in [k for k, v in _TICKETS.items() if v["exp"] < now]:
        _TICKETS.pop(k, None)
    t = secrets.token_urlsafe(24)
    _TICKETS[t] = {"project_id": project_id, "tokens": dict(tokens), "exp": now + TICKET_TTL}
    return t


def token_for(ticket: str, project_id: str, target: str) -> str | None:
    t = _TICKETS.get(ticket or "")
    if not t or t["exp"] < time.time() or t["project_id"] != project_id:
        return None
    return t["tokens"].get(target)


def add_to_tickets(project_id: str, target: str, token: str) -> None:
    for t in _TICKETS.values():
        if t["project_id"] == project_id and t["exp"] >= time.time():
            t["tokens"][target] = token


def revoke(ticket: str | None = None, project_id: str | None = None, target: str | None = None) -> None:
    for k in [k for k, v in _TICKETS.items() if k == ticket or (project_id and v["project_id"] == project_id)]:
        if target:
            _TICKETS[k]["tokens"].pop(target, None)
        else:
            _TICKETS.pop(k, None)
