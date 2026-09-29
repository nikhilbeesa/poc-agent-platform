"""
Tiny in-process background-job runner for long LIVE-mode steps.

Chunked live generation makes dozens of LLM calls per agent, which can run
for minutes — far past the gunicorn/proxy request timeout if done inside one
HTTP request. So the request handler starts the work here and returns a job
id immediately; the browser polls GET /api/job/<id> for progress and the
final result (the same JSON the synchronous endpoint would have returned).

State is in memory, like PROJECTS: fine for this single-worker POC, and it
is deliberately not shared across processes.
"""

from __future__ import annotations

import threading
import time
import uuid

import chunked

_JOBS: dict[str, dict] = {}
_ACTIVE: dict[str, str] = {}   # project_id -> running job id
_LOCK = threading.Lock()
_KEEP_SECONDS = 1800
_MAX_PROGRESS_LINES = 60


def _push(job: dict, message: str) -> None:
    """Appends a progress line; consecutive lines of the same stage
    ("Label: 3/12" -> "Label: 4/12") replace each other instead of piling up."""
    label = message.split(":")[0] + ":" if ":" in message else None
    lines = job["progress"]
    if label and lines and lines[-1].startswith(label):
        lines[-1] = message
    else:
        lines.append(message)
        if len(lines) > _MAX_PROGRESS_LINES:
            del lines[0]
    job["updated"] = time.time()


def start(project_id: str, work) -> str:
    """Runs work() (a zero-arg callable returning a JSON-able dict) in a
    background thread. If a job for this project is already running, returns
    ITS id instead of starting a second one, so a double-click or a retry
    after a page refresh can never run two generations against one project."""
    with _LOCK:
        now = time.time()
        for jid in [j for j, v in _JOBS.items() if v["status"] != "running" and now - v["updated"] > _KEEP_SECONDS]:
            _JOBS.pop(jid, None)
        running = _ACTIVE.get(project_id)
        if running and _JOBS.get(running, {}).get("status") == "running":
            return running
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "project_id": project_id, "status": "running", "progress": [],
               "result": None, "error": None, "started": now, "updated": now}
        _JOBS[job_id] = job
        _ACTIVE[project_id] = job_id

    def runner():
        chunked.set_progress_callback(lambda m: _push(job, m))
        try:
            result = work()
            job["result"] = result
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            job["error"] = f"{type(e).__name__}: {e}"
            job["status"] = "error"
        finally:
            job["updated"] = time.time()

    threading.Thread(target=runner, daemon=True, name=f"job-{job_id}").start()
    return job_id


def snapshot(job_id: str) -> dict | None:
    job = _JOBS.get(job_id)
    if job is None:
        return None
    return {
        "status": job["status"],
        "progress": list(job["progress"]),
        "elapsed": round(time.time() - job["started"], 1),
        "result": job["result"] if job["status"] == "done" else None,
        "error": job["error"],
    }
