"""
Entry points used by the web server: connect/check, preview, and push (as a background job with live progress).

Safe to run repeatedly: what was created is remembered per project AND per target (context.integration_links, no
secrets), so a second push creates only what is new, updates what changed (if asked), and never duplicates.
Credentials are used for the one request and are never stored, logged or returned.
"""

from __future__ import annotations

import threading
import time
import uuid

from context import ProjectContext
from .azure_devops import AzureDevOps
from .backlog import build_backlog
from .http import IntegrationError
from .jira import Jira

TARGETS = ("jira", "ado")


def connect(target: str, creds: dict):
    if target == "jira":
        return Jira(creds.get("base_url", ""), creds.get("email", ""), creds.get("token", ""), creds.get("project", ""))
    if target == "ado":
        return AzureDevOps(creds.get("base_url", ""), creds.get("project", ""), creds.get("token", ""))
    raise IntegrationError("Unknown target.")


def check(target: str, creds: dict) -> dict:
    return connect(target, creds).check()


def preview(context: ProjectContext, target: str, creds: dict | None = None) -> dict:
    """What a push would do — no calls to the tool when credentials are not given."""
    bk = build_backlog(context)
    done = {}
    if creds:
        try:
            done = context.integration_links.get(connect(target, creds).target_id, {})
        except IntegrationError:
            pass
    stories = bk["stories"]
    return {"epics": len(bk["epics"]), "stories": len(stories),
            "already_pushed": sum(1 for x in bk["epics"] + stories if x["id"] in done),
            "by_priority": {p: sum(1 for s in stories if s["priority"] == p) for p in ("High", "Medium", "Low")},
            "dependencies": sum(len(s["dependencies"]) for s in stories),
            "sample": [{"id": s["id"], "title": s["title"], "priority": s["priority"], "epic": s["epic_id"]} for s in stories[:5]]}


def push(context: ProjectContext, target: str, creds: dict, options: dict, progress=lambda m: None) -> dict:
    t0 = time.time()
    bk = build_backlog(context)
    if not bk["stories"]:
        raise IntegrationError("There are no user stories yet — run the agent team first.")
    tool = connect(target, creds)
    tool.check()
    update = bool(options.get("update_existing"))
    store = context.integration_links.setdefault(tool.target_id, {})
    rep = {"created": 0, "updated": 0, "unchanged": 0, "failed": [], "items": [], "dependency_links": 0}

    def record(it, ref, status):
        rep["items"].append({"id": it["id"], "kind": it["kind"], "title": it["title"], "key": ref.get("key", ""),
                             "url": ref.get("url", ""), "status": status})

    total = len(bk["epics"]) + len(bk["stories"])
    n = 0
    for it in bk["epics"] + bk["stories"]:
        n += 1
        progress(f"Sending: {n}/{total}")
        ref = store.get(it["id"])
        try:
            if ref and ref.get("key"):
                if update and ref.get("hash") != it["hash"]:
                    tool.update(ref, it)
                    ref["hash"] = it["hash"]
                    rep["updated"] += 1
                    record(it, ref, "updated")
                else:
                    rep["unchanged"] += 1
                    record(it, ref, "unchanged")
                continue
            if it["kind"] == "epic":
                ref = tool.create_epic(it)
            else:
                ref = tool.create_story(it, store.get(it["epic_id"]))
            if not ref:                       # tool has no epic type: nothing to remember
                continue
            store[it["id"]] = {**ref, "hash": it["hash"], "linked": []}
            rep["created"] += 1
            record(it, ref, "created")
        except IntegrationError as e:
            rep["failed"].append({"id": it["id"], "title": it["title"], "error": str(e)})

    # dependencies last, so every prerequisite already exists in the tool
    for it in bk["stories"]:
        me = store.get(it["id"])
        for dep in it["dependencies"]:
            other = store.get(dep)
            if not (me and other) or dep in me.setdefault("linked", []):
                continue
            try:
                tool.link_dependency(me, other)
                me["linked"].append(dep)
                rep["dependency_links"] += 1
            except IntegrationError as e:
                rep["failed"].append({"id": it["id"], "title": f"link {it['id']} → {dep}", "error": str(e)})
    rep["warnings"] = list(dict.fromkeys(tool.warnings))
    rep["target"], rep["seconds"] = tool.target_id, round(time.time() - t0, 1)
    return rep


# ---- background jobs (a push of 70+ stories outlasts a normal HTTP request) --------------------
_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def start_push(project_id: str, context: ProjectContext, target: str, creds: dict, options: dict, on_done) -> str:
    """One push per project at a time. creds live only in this thread's closure and are dropped when it ends."""
    with _LOCK:
        for jid, j in _JOBS.items():
            if j["project_id"] == project_id and j["status"] == "running":
                return jid
        jid = uuid.uuid4().hex[:12]
        job = _JOBS[jid] = {"id": jid, "project_id": project_id, "status": "running", "progress": "Connecting…",
                            "result": None, "error": None, "updated": time.time()}
        for old in [k for k, v in _JOBS.items() if v["status"] != "running" and time.time() - v["updated"] > 1800]:
            _JOBS.pop(old, None)

    def run():
        try:
            job["result"] = push(context, target, creds, options, lambda m: job.update(progress=m, updated=time.time()))
            on_done()
            job["status"] = "done"
        except IntegrationError as e:
            job["error"], job["status"] = str(e), "error"
        except Exception as e:  # noqa: BLE001 — never leak internals/secrets to the browser
            job["error"], job["status"] = f"Unexpected error ({type(e).__name__}). Nothing sensitive was logged.", "error"
        finally:
            job["updated"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"push-{jid}").start()
    return jid


def job_status(project_id: str, job_id: str) -> dict | None:
    j = _JOBS.get(job_id)
    return None if not j or j["project_id"] != project_id else {k: j[k] for k in ("status", "progress", "result", "error")}
