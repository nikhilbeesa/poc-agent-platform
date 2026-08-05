"""
Knowledge Store
================
Persisted storage for domain knowledge. Two backends sharing the same
interface (list_domains, domain_exists, get_domain, save_domain):

- KnowledgeStore       — flat JSON files under data/domains/. Zero setup,
                          used for local development.
- SupabaseKnowledgeStore — a `domains` table in Supabase Postgres, used
                          in production so knowledge persists centrally
                          instead of living on a single server's disk
                          (which Render's free tier doesn't even
                          guarantee across deploys).

get_knowledge_store() picks automatically: Supabase if SUPABASE_URL and
SUPABASE_KEY are set, otherwise the local file store. Nothing that calls
the store needs to know or care which backend is active — see Section 7
of the spec: the storage technology is an implementation detail, not an
architecture decision.

Each domain has this shape either way:
{
  "name": "human-readable name",
  "description": "...",
  "typical_modules": ["...", "..."],
  "seed_questions": [{"id": "...", "text": "...", "category": "..."}]
}
"""

import json
import os
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent / "data" / "domains"


class KnowledgeStore:
    """Local file-backed store. Used when Supabase isn't configured."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def list_domains(self) -> list[str]:
        return sorted(p.stem for p in self.data_dir.glob("*.json"))

    def domain_exists(self, name: str) -> bool:
        return (self.data_dir / f"{name}.json").exists()

    def get_domain(self, name: str) -> dict | None:
        path = self.data_dir / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_domain(self, name: str, domain: dict) -> None:
        path = self.data_dir / f"{name}.json"
        path.write_text(json.dumps(domain, indent=2))

    def get_all(self) -> dict:
        return {name: self.get_domain(name) for name in self.list_domains()}


class SupabaseKnowledgeStore:
    """Supabase Postgres-backed store, via the PostgREST HTTP API — no
    extra client library needed, just `requests`, so this works anywhere
    (Render, Netlify functions, local) without dependency friction.

    Requires the `domains` table from deploy/supabase_schema.sql to
    already exist in the target Supabase project.
    """

    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = key or os.environ["SUPABASE_KEY"]
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, path: str = "") -> str:
        return f"{self.url}/rest/v1/domains{path}"

    def list_domains(self) -> list[str]:
        resp = requests.get(self._endpoint("?select=slug"), headers=self._headers, timeout=10)
        resp.raise_for_status()
        return sorted(row["slug"] for row in resp.json())

    def domain_exists(self, name: str) -> bool:
        return self.get_domain(name) is not None

    def get_domain(self, name: str) -> dict | None:
        resp = requests.get(
            self._endpoint(f"?slug=eq.{name}&select=*"),
            headers=self._headers, timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        return {
            "name": row["name"],
            "description": row["description"],
            "typical_modules": row["typical_modules"],
            "seed_questions": row["seed_questions"],
        }

    def save_domain(self, name: str, domain: dict) -> None:
        payload = {
            "slug": name,
            "name": domain.get("name", name),
            "description": domain.get("description", ""),
            "typical_modules": domain.get("typical_modules", []),
            "seed_questions": domain.get("seed_questions", []),
        }
        # Upsert — Prefer header tells PostgREST to insert-or-update on
        # the primary key conflict rather than erroring on duplicates.
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates"}
        resp = requests.post(self._endpoint(), headers=headers, json=payload, timeout=10)
        resp.raise_for_status()

    def get_all(self) -> dict:
        return {name: self.get_domain(name) for name in self.list_domains()}


def get_knowledge_store():
    """Returns the Supabase-backed store if configured, otherwise the
    local file store. This is the ONLY place code should decide which
    backend to use — everything else just calls the interface."""
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        return SupabaseKnowledgeStore()
    return KnowledgeStore()
