"""Jira Cloud (REST API v3). Auth: account email + API token (https://id.atlassian.com/manage-profile/security/api-tokens)."""

from __future__ import annotations

import re

from . import backlog as bl
from .http import IntegrationError, call, validate_url


class Jira:
    name = "Jira"

    def __init__(self, base_url: str, email: str, token: str, project_key: str):
        self.base = validate_url(base_url, (".atlassian.net",), "JIRA_ALLOWED_HOSTS")
        if not (email and token):
            raise IntegrationError("Enter your Atlassian email and API token.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{1,24}$", project_key or ""):
            raise IntegrationError("Enter the project key (letters/digits, e.g. APP).")
        self.auth, self.key, self.secrets = (email, token), project_key.upper(), (token,)
        self.epic_type = self.story_type = None
        self.warnings: list[str] = []

    @property
    def target_id(self) -> str:
        return f"jira:{self.base.split('//')[1]}:{self.key}"

    def _c(self, method, path, json=None):
        return call(method, f"{self.base}/rest/api/3{path}", auth=self.auth, json=json, secrets=self.secrets)

    def check(self) -> dict:
        _, me = self._c("GET", "/myself")
        _, proj = self._c("GET", f"/project/{self.key}")
        types = {t["name"]: t for t in (proj or {}).get("issueTypes", [])}
        self.epic_type = "Epic" if "Epic" in types else None
        self.story_type = "Story" if "Story" in types else ("Task" if "Task" in types else None)
        if not self.epic_type:
            self.warnings.append("This project has no Epic issue type — stories will be created without an epic.")
        if not self.story_type:
            raise IntegrationError("This project has neither a Story nor a Task issue type to create stories with.")
        if self.story_type == "Task":
            self.warnings.append("No Story issue type here — using Task instead.")
        return {"user": (me or {}).get("displayName", ""), "project": (proj or {}).get("name", self.key),
                "epic_type": self.epic_type, "story_type": self.story_type, "warnings": list(self.warnings)}

    # -- writes -------------------------------------------------------------------------------
    def _create(self, fields: dict, item: dict) -> dict:
        """Create an issue; if the project's screen rejects an optional field (priority, labels, parent) or an old
        company-managed project demands an 'Epic Name', fix that one thing and retry — never fail the whole story."""
        optional = ("priority", "labels", "parent")
        for _ in range(4):
            try:
                _, body = self._c("POST", "/issue", {"fields": fields})
                return body
            except IntegrationError as e:
                errs = ((e.details.get("body") or {}).get("errors") or {}) if e.status == 400 else {}
                dropped = [k for k in errs if k in optional and k in fields]
                epic_name = [k for k, v in errs.items() if k.startswith("customfield_") and "epic name" in str(v).lower()]
                if not dropped and not epic_name:
                    raise
                for k in dropped:
                    fields.pop(k)
                    self.warnings.append(f"“{k}” is not available on this project, so it was left out.")
                for k in epic_name:
                    fields[k] = item.get("name") or item["title"]
        raise IntegrationError("Jira kept rejecting the issue fields.")

    def _fields(self, item: dict, type_name: str) -> dict:
        f = {"project": {"key": self.key}, "summary": item["title"], "issuetype": {"name": type_name},
             "description": bl.to_adf(item), "labels": item.get("labels", [])}
        if item["kind"] == "story":
            f["priority"] = {"name": item["priority"]}
        return f

    def create_epic(self, item: dict) -> dict:
        if not self.epic_type:
            return {}
        b = self._create(self._fields(item, self.epic_type), item)
        return {"key": b["key"], "url": f"{self.base}/browse/{b['key']}"}

    def create_story(self, item: dict, epic_ref: dict | None) -> dict:
        f = self._fields(item, self.story_type)
        if epic_ref and epic_ref.get("key"):
            f["parent"] = {"key": epic_ref["key"]}
        b = self._create(f, item)
        return {"key": b["key"], "url": f"{self.base}/browse/{b['key']}"}

    def update(self, ref: dict, item: dict) -> None:
        self._c("PUT", f"/issue/{ref['key']}", {"fields": {"summary": item["title"], "description": bl.to_adf(item),
                                                           "labels": item.get("labels", [])}})

    def link_dependency(self, story_ref: dict, depends_on_ref: dict) -> None:
        """'depends_on' blocks 'story' — so the prerequisite is the OUTWARD ('blocks') side."""
        self._c("POST", "/issueLink", {"type": {"name": "Blocks"}, "outwardIssue": {"key": depends_on_ref["key"]},
                                       "inwardIssue": {"key": story_ref["key"]}})
