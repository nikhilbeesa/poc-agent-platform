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
    questions = record.get("questions") or []
    artefacts = record.get("artefacts") or []
    return {
        "id": record["id"], "business_idea": record["business_idea"], "domain": record.get("domain"),
        "handoff_status": record.get("handoff_status"),
        # "draft" = discovery / agents not finished yet (resumable); "complete" = artefacts exist
        "status": record.get("status") or ("complete" if artefacts else "draft"),
        "artefact_count": len(artefacts),
        "question_count": len(questions),
        "answered_count": len([q for q in questions if q.get("status") in ("answered", "skipped")]),
        "created_at": record.get("created_at"), "updated_at": record.get("updated_at"),
    }


class ProjectStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict) -> None:
        record = dict(record)
        now = datetime.now(timezone.utc).isoformat()
        path = self.data_dir / f"{record['id']}.json"
        if not record.get("created_at"):
            # re-saving a project (draft autosave, re-run) must keep its original creation time
            try:
                record["created_at"] = json.loads(path.read_text()).get("created_at") or now
            except (OSError, ValueError):
                record["created_at"] = now
        record["updated_at"] = now
        path.write_text(json.dumps(record, indent=2, default=str))

    def delete(self, project_id: str) -> None:
        path = self.data_dir / f"{project_id}.json"
        if path.exists():
            path.unlink()

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
            "status": record.get("status", "complete"), "questions": record.get("questions", []),
            "agent_log": record.get("agent_log", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if record.get("created_at"):
            payload["created_at"] = record["created_at"]
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates"}
        # Feasibility summary + shared system profile live in two newer columns (see deploy/supabase_schema.sql).
        # If the database has not been migrated yet, Supabase answers 400 for the unknown columns — in that case
        # save WITHOUT them instead of failing, so an un-migrated deployment keeps working (the profile is
        # rebuilt deterministically from the stored answers when a project is reopened).
        extra = {"system_profile": record.get("system_profile"), "feasibility": record.get("feasibility")}
        if getattr(self, "_warned_missing_columns", False):
            extra = {}          # already known to be missing — don't waste a round trip each save
        resp = requests.post(self._endpoint(), headers=headers, json={**payload, **extra}, timeout=15)
        if extra and resp.status_code == 400 and any(k in resp.text for k in extra):
            if not getattr(self, "_warned_missing_columns", False):
                logger.warning("Supabase `projects` table lacks system_profile/feasibility columns — run the latest "
                               "deploy/supabase_schema.sql. Saving without them.")
                self._warned_missing_columns = True
            resp = requests.post(self._endpoint(), headers=headers, json=payload, timeout=15)
        resp.raise_for_status()

    def delete(self, project_id: str) -> None:
        resp = requests.delete(self._endpoint(f"?id=eq.{project_id}"), headers=self._headers, timeout=15)
        resp.raise_for_status()

    def list_summaries(self, limit: int = 50) -> list:
        resp = requests.get(
            self._endpoint(f"?select=id,business_idea,domain,handoff_status,status,artefacts,questions,created_at,updated_at&order=updated_at.desc.nullslast&limit={limit}"),
            headers=self._headers, timeout=15,
        )
        resp.raise_for_status()
        return [_project_summary({**row, "artefacts": row.get("artefacts") or [], "questions": row.get("questions") or []}) for row in resp.json()]

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

    def delete(self, project_id: str) -> None:
        return self._call("delete", project_id)
