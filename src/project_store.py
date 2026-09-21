"""
Project Store — persists completed projects so they survive server
restarts and power the History dashboard. Dual backend: local file or
Supabase, chosen automatically via env vars.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "knowledge" / "data" / "projects"


def _project_summary(record: dict) -> dict:
    return {
        "id": record["id"], "business_idea": record["business_idea"], "domain": record.get("domain"),
        "handoff_status": record.get("handoff_status"),
        "artefact_count": len(record.get("artefacts", [])), "created_at": record.get("created_at"),
    }


class ProjectStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict) -> None:
        record = dict(record)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        (self.data_dir / f"{record['id']}.json").write_text(json.dumps(record, indent=2, default=str))

    def list_summaries(self, limit: int = 50) -> list:
        files = sorted(self.data_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        records = [json.loads(p.read_text()) for p in files[:limit]]
        return [_project_summary(r) for r in records]

    def get(self, project_id: str):
        path = self.data_dir / f"{project_id}.json"
        return json.loads(path.read_text()) if path.exists() else None


class SupabaseProjectStore:
    def __init__(self, url: str = None, key: str = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = key or os.environ["SUPABASE_KEY"]
        self._headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _endpoint(self, path: str = "") -> str:
        return f"{self.url}/rest/v1/projects{path}"

    def save(self, record: dict) -> None:
        payload = {
            "id": record["id"], "business_idea": record["business_idea"], "domain": record.get("domain"),
            "domain_confidence": record.get("domain_confidence"), "stage": record.get("stage", "complete"),
            "handoff_status": record.get("handoff_status"), "consistency_notes": record.get("consistency_notes", []),
            "artefacts": record.get("artefacts", []),
        }
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates"}
        resp = requests.post(self._endpoint(), headers=headers, json=payload, timeout=15)
        resp.raise_for_status()

    def list_summaries(self, limit: int = 50) -> list:
        resp = requests.get(
            self._endpoint(f"?select=id,business_idea,domain,handoff_status,artefacts,created_at&order=created_at.desc&limit={limit}"),
            headers=self._headers, timeout=15,
        )
        resp.raise_for_status()
        return [_project_summary({**row, "artefacts": row.get("artefacts") or []}) for row in resp.json()]

    def get(self, project_id: str):
        resp = requests.get(self._endpoint(f"?id=eq.{project_id}&select=*"), headers=self._headers, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


_project_store_singleton = None


def get_project_store():
    global _project_store_singleton
    if _project_store_singleton is None:
        if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
            _project_store_singleton = ResilientProjectStore(SupabaseProjectStore(), ProjectStore())
        else:
            _project_store_singleton = ProjectStore()
    return _project_store_singleton


class ResilientProjectStore:
    """Wraps a primary store (normally Supabase) with a local-file
    fallback — see ResilientKnowledgeStore in knowledge/store.py for the
    full rationale. Degrades transparently on connection failure instead
    of taking down the request."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self._primary_down = False

    def _call(self, method_name: str, *args, **kwargs):
        if not self._primary_down:
            try:
                return getattr(self.primary, method_name)(*args, **kwargs)
            except requests.exceptions.RequestException as e:
                self._primary_down = True
                logger.warning(
                    "Project store primary backend (Supabase) unreachable — "
                    "falling back to local storage for the rest of this process. "
                    "Check SUPABASE_URL/SUPABASE_KEY. Error: %s", e,
                )
        return getattr(self.fallback, method_name)(*args, **kwargs)

    def save(self, record: dict) -> None:
        return self._call("save", record)

    def list_summaries(self, limit: int = 50) -> list:
        return self._call("list_summaries", limit)

    def get(self, project_id: str):
        return self._call("get", project_id)
