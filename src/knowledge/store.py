import json
import logging
import os
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data" / "domains"


class KnowledgeStore:
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
        (self.data_dir / f"{name}.json").write_text(json.dumps(domain, indent=2))

    def get_all(self) -> dict:
        return {name: self.get_domain(name) for name in self.list_domains()}


class SupabaseKnowledgeStore:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = key or os.environ["SUPABASE_KEY"]
        self._headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _endpoint(self, path: str = "") -> str:
        return f"{self.url}/rest/v1/domains{path}"

    def list_domains(self) -> list[str]:
        resp = requests.get(self._endpoint("?select=slug"), headers=self._headers, timeout=10)
        resp.raise_for_status()
        return sorted(row["slug"] for row in resp.json())

    def domain_exists(self, name: str) -> bool:
        return self.get_domain(name) is not None

    def get_domain(self, name: str) -> dict | None:
        resp = requests.get(self._endpoint(f"?slug=eq.{name}&select=*"), headers=self._headers, timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        return {"name": row["name"], "description": row["description"], "typical_modules": row["typical_modules"], "seed_questions": row["seed_questions"]}

    def save_domain(self, name: str, domain: dict) -> None:
        payload = {"slug": name, "name": domain.get("name", name), "description": domain.get("description", ""),
                   "typical_modules": domain.get("typical_modules", []), "seed_questions": domain.get("seed_questions", [])}
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates"}
        resp = requests.post(self._endpoint(), headers=headers, json=payload, timeout=15)
        resp.raise_for_status()

    def get_all(self) -> dict:
        return {name: self.get_domain(name) for name in self.list_domains()}


_knowledge_store_singleton = None


def get_knowledge_store():
    global _knowledge_store_singleton
    if _knowledge_store_singleton is None:
        if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
            _knowledge_store_singleton = ResilientKnowledgeStore(SupabaseKnowledgeStore(), KnowledgeStore())
        else:
            _knowledge_store_singleton = KnowledgeStore()
    return _knowledge_store_singleton


class ResilientKnowledgeStore:
    """Wraps a primary store (normally Supabase) with a local-file
    fallback. If the primary store becomes unreachable — DNS failure,
    connection refused, timeout, paused project, etc. — every method
    call transparently degrades to the local store instead of raising
    and taking down the whole request. Once a failure is seen, later
    calls in this process skip straight to the fallback (no per-request
    retry delay); a fresh deploy/restart will try the primary again.
    """

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
                    "Knowledge store primary backend (Supabase) unreachable — "
                    "falling back to local storage for the rest of this process. "
                    "Check SUPABASE_URL/SUPABASE_KEY. Error: %s", e,
                )
        return getattr(self.fallback, method_name)(*args, **kwargs)

    def list_domains(self) -> list[str]:
        return self._call("list_domains")

    def domain_exists(self, name: str) -> bool:
        return self._call("domain_exists", name)

    def get_domain(self, name: str) -> dict | None:
        return self._call("get_domain", name)

    def save_domain(self, name: str, domain: dict) -> None:
        return self._call("save_domain", name, domain)

    def get_all(self) -> dict:
        return self._call("get_all")
