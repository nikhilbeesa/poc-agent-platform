import json
import os
from pathlib import Path
import requests

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


def get_knowledge_store():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        return SupabaseKnowledgeStore()
    return KnowledgeStore()
