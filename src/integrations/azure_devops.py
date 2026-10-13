"""Azure DevOps Services (REST API 7.1). Auth: a Personal Access Token with Work Items (Read & write) scope."""

from __future__ import annotations

import re

from . import backlog as bl
from .http import IntegrationError, call, validate_url

API = "api-version=7.1"
PRIORITY = {"High": 2, "Medium": 3, "Low": 4}
# the story type depends on the project's process template
STORY_TYPES = [("User Story", "Agile"), ("Product Backlog Item", "Scrum"), ("Requirement", "CMMI"), ("Issue", "Basic")]


class AzureDevOps:
    name = "Azure DevOps"

    def __init__(self, org_url: str, project: str, pat: str):
        org_url = (org_url or "").strip()
        if org_url and "//" not in org_url:                     # allow just the organisation name
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,49}$", org_url):
                raise IntegrationError("Enter your organisation name or https://dev.azure.com/<organisation>")
            org_url = f"https://dev.azure.com/{org_url}"
        parts = org_url.rstrip("/").split("/", 3)
        self.base = validate_url("/".join(parts[:3]), ("dev.azure.com", ".visualstudio.com"), "ADO_ALLOWED_HOSTS")
        self.org_path = parts[3] if len(parts) > 3 else ""      # dev.azure.com/<org>
        if self.base.endswith("dev.azure.com") and not self.org_path:
            raise IntegrationError("Include your organisation: https://dev.azure.com/<organisation>")
        if not (project or "").strip() or not pat:
            raise IntegrationError("Enter the project name and a personal access token.")
        self.project, self.auth, self.secrets = project.strip(), ("", pat), (pat,)
        self.root = f"{self.base}/{self.org_path}".rstrip("/")
        self.epic_type, self.story_type, self.process = None, None, ""
        self.warnings: list[str] = []
        self.tags_denied = False           # True once Azure DevOps refuses to create a NEW tag for this account
        self.ok_tags: set[str] = set()     # tags that already exist (a work item carrying them was created fine)

    @property
    def target_id(self) -> str:
        return f"ado:{self.root.split('//')[1]}/{self.project}"

    def _c(self, method, path, json=None, patch=False):
        sep = "&" if "?" in path else "?"
        return call(method, f"{self.root}{path}{sep}{API}", auth=self.auth, json=json, secrets=self.secrets,
                    headers={"Content-Type": "application/json-patch+json"} if patch else None)

    def check(self) -> dict:
        _, proj = self._c("GET", f"/_apis/projects/{self.project}")
        _, wit = self._c("GET", f"/{self.project}/_apis/wit/workitemtypes")
        names = {t["name"] for t in (wit or {}).get("value", [])}
        self.epic_type = "Epic" if "Epic" in names else None
        for t, proc in STORY_TYPES:
            if t in names:
                self.story_type, self.process = t, proc
                break
        if not self.story_type:
            raise IntegrationError("Could not find a user-story work item type in this project.")
        if not self.epic_type:
            self.warnings.append("This project's process has no Epic type — stories will be created without an epic.")
        # Reading work items and CREATING them need different token scopes, so "connected" proves little. validateOnly runs
        # Azure DevOps' own create checks (permission, type, fields) without creating anything.
        try:
            self._c("POST", f"/{self.project}/_apis/wit/workitems/${self.story_type}?validateOnly=true",
                    [{"op": "add", "path": "/fields/System.Title", "value": "connection test"}], patch=True)
        except IntegrationError as e:
            if e.status in (401, 403):
                raise IntegrationError("Connected, but this token cannot create work items. Recreate it with the “Work Items: Read & write” scope. "
                                       f"({e})", e.status)
            self.warnings.append(f"Could not pre-check creating a {self.story_type} ({e}).")
        return {"user": "", "project": (proj or {}).get("name", self.project), "epic_type": self.epic_type,
                "story_type": self.story_type, "process": self.process, "warnings": list(self.warnings)}

    # -- writes -------------------------------------------------------------------------------
    def _ops(self, item: dict, type_name: str, op: str = "add") -> list[dict]:
        has_ac = item["kind"] == "story" and type_name in ("User Story", "Product Backlog Item", "Requirement")
        ops = [("System.Title", item["title"]), ("System.Description", bl.to_html(item, with_acceptance=not has_ac)),
               ("System.Tags", "; ".join(item.get("labels", [])))]
        if item["kind"] == "story":
            ops.append(("Microsoft.VSTS.Common.Priority", PRIORITY.get(item["priority"], 3)))
            if has_ac:
                ops.append(("Microsoft.VSTS.Common.AcceptanceCriteria", bl.to_acceptance_html(item)))
        return [{"op": op, "path": f"/fields/{k}", "value": v} for k, v in ops]

    @staticmethod
    def _tag_list(ops: list[dict]) -> list[str]:
        v = next((o["value"] for o in ops if o["path"] == "/fields/System.Tags"), "")
        return [t.strip() for t in str(v).split(";") if t.strip()]

    @staticmethod
    def _set_tags(ops: list[dict], tags: list[str]) -> list[dict]:
        ops = [o for o in ops if o["path"] != "/fields/System.Tags"]
        if tags:
            ops.append({"op": next((o["op"] for o in ops), "add"), "path": "/fields/System.Tags", "value": "; ".join(tags)})
        return ops

    def _send(self, method, path, ops):
        """Drop an optional field the process doesn't have (ADO names it in the error) and retry.

        Tags need special care: creating a work item with a tag that does not exist yet needs the separate
        'Create tag definition' permission (TF401289). Without it, every story carrying a new tag (its module name,
        its FR-id) is refused while epics (only the long-existing 'ai-generated' tag) go through — leaving an
        epics-only backlog. So when that happens we keep only tags that already exist, and if none are left we
        send the work item without tags: the content is far more important than the tag."""
        if self.tags_denied:                                   # learned earlier in this push: don't fail once per item
            ops = self._set_tags(ops, [t for t in self._tag_list(ops) if t in self.ok_tags])
        for _ in range(5):
            try:
                _, body = self._c(method, path, ops, patch=True)
                self.ok_tags.update(self._tag_list(ops))
                return body
            except IntegrationError as e:
                if e.status in (400, 401, 403) and "TF401289" in str(e) and self._tag_list(ops):
                    self.tags_denied = True
                    kept = [t for t in self._tag_list(ops) if t in self.ok_tags]
                    ops = self._set_tags(ops, kept)
                    self.warnings.append(
                        "Some tags were left off: this account is not allowed to create NEW tags in the project (TF401289). "
                        "Work items were still created. To keep the tags, ask a project administrator to give this user "
                        "“Create tag definition” (Project settings → Permissions → the user → Create tag definition = Allow), then Send again with “update existing”.")
                    continue
                bad = [o for o in ops if o["path"].startswith("/fields/") and o["path"].split("/")[-1] in str(e)
                       and o["path"].split("/")[-1] != "System.Title"]
                if e.status != 400 or not bad:
                    raise
                ops = [o for o in ops if o not in bad]
                self.warnings += [f"Field {o['path'].split('/')[-1]} does not exist in this process, so it was left out." for o in bad]
        raise IntegrationError("Azure DevOps kept rejecting the work item fields.")

    def _ref(self, body: dict) -> dict:
        if not isinstance(body, dict) or "id" not in body:
            raise IntegrationError("Azure DevOps did not return the new work item — nothing was created.")
        return {"key": str(body["id"]), "url": ((body.get("_links") or {}).get("html") or {}).get("href")
                or f"{self.root}/{self.project}/_workitems/edit/{body['id']}", "api_url": body.get("url", "")}

    def create_epic(self, item: dict) -> dict:
        if not self.epic_type:
            return {}
        return self._ref(self._send("POST", f"/{self.project}/_apis/wit/workitems/${self.epic_type}", self._ops(item, self.epic_type)))

    def create_story(self, item: dict, epic_ref: dict | None) -> dict:
        ops = self._ops(item, self.story_type)
        if epic_ref and epic_ref.get("api_url"):
            ops.append({"op": "add", "path": "/relations/-", "value": {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": epic_ref["api_url"]}})
        return self._ref(self._send("POST", f"/{self.project}/_apis/wit/workitems/${self.story_type}", ops))

    def update(self, ref: dict, item: dict) -> None:
        t = self.epic_type if item["kind"] == "epic" else self.story_type
        self._send("PATCH", f"/{self.project}/_apis/wit/workitems/{ref['key']}", self._ops(item, t, op="replace"))

    def link_dependency(self, story_ref: dict, depends_on_ref: dict) -> None:
        """The prerequisite is the story's PREDECESSOR (System.LinkTypes.Dependency-Reverse)."""
        self._send("PATCH", f"/{self.project}/_apis/wit/workitems/{story_ref['key']}",
                   [{"op": "add", "path": "/relations/-", "value": {"rel": "System.LinkTypes.Dependency-Reverse",
                                                                     "url": depends_on_ref.get("api_url") or f"{self.root}/_apis/wit/workItems/{depends_on_ref['key']}"}}])
