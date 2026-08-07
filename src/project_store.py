"""
Project Store
==============
Persists completed projects (idea, domain, artefacts) so they survive
server restarts and can be browsed later — the "History" view in the
web UI. Same dual-backend pattern as knowledge/store.py: a local
file-backed store for development, a Supabase-backed one for production,
chosen automatically via the same env vars.

Deliberately only persists at EXPORT time (once artefacts exist) — an
in-progress project (mid-discovery, mid-agent-run) stays in the
in-memory PROJECTS dict in webapp/server.py as before. This keeps the
history view meaningful: it shows finished work, not half-finished
sessions someone abandoned.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent / "knowledge" / "data" / "projects"


def _project_summary(record: dict) -> dict:
    """Trimmed-down view for list endpoints — no full artefact content."""
    return {
        "id": record["id"],
        "business_idea": record["business_idea"],
        "domain": record.get("domain"),
        "qa_readiness": record.get("qa_readiness"),
        "artefact_count": len(record.get("artefacts", [])),
        "created_at": record.get("created_at"),
    }


class ProjectStore:
    """Local file-backed store — one JSON file per project."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict) -> None:
        record = dict(record)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        path = self.data_dir / f"{record['id']}.json"
        path.write_text(json.dumps(record, indent=2, default=str))

    def list_summaries(self, limit: int = 50) -> list[dict]:
        files = sorted(self.data_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        records = [json.loads(p.read_text()) for p in files[:limit]]
        return [_project_summary(r) for r in records]

    def get(self, project_id: str) -> dict | None:
        path = self.data_dir / f"{project_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())


class SupabaseProjectStore:
    """Supabase Postgres-backed store via the PostgREST HTTP API."""

    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = key or os.environ["SUPABASE_KEY"]
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, path: str = "") -> str:
        return f"{self.url}/rest/v1/projects{path}"

    def save(self, record: dict) -> None:
        payload = {
            "id": record["id"],
            "business_idea": record["business_idea"],
            "domain": record.get("domain"),
            "domain_confidence": record.get("domain_confidence"),
            "stage": record.get("stage", "complete"),
            "qa_readiness": record.get("qa_readiness"),
            "consistency_notes": record.get("consistency_notes", []),
            "artefacts": record.get("artefacts", []),
        }
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates"}
        resp = requests.post(self._endpoint(), headers=headers, json=payload, timeout=15)
        resp.raise_for_status()

    def list_summaries(self, limit: int = 50) -> list[dict]:
        resp = requests.get(
            self._endpoint(
                f"?select=id,business_idea,domain,qa_readiness,artefacts,created_at"
                f"&order=created_at.desc&limit={limit}"
            ),
            headers=self._headers, timeout=15,
        )
        resp.raise_for_status()
        return [_project_summary({**row, "artefacts": row.get("artefacts") or []}) for row in resp.json()]

    def get(self, project_id: str) -> dict | None:
        resp = requests.get(
            self._endpoint(f"?id=eq.{project_id}&select=*"),
            headers=self._headers, timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


def get_project_store():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        return SupabaseProjectStore()
    return ProjectStore()
