"""
Logging setup
=============
Every agent call gets logged: which agent ran, what it was given, what it
produced, and when. This is what makes the system auditable later (Section 9
of the spec — "observability and auditability").

Deterministic logic — no AI involved. Logs go to logs/agent_activity.log as
JSON lines, so they're easy to parse later for a dashboard or debugging.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "agent_activity.log"


def get_logger(name: str = "poc_platform") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers on re-import

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    return logger


def log_agent_call(
    logger: logging.Logger,
    project_id: str,
    agent: str,
    event: str,
    detail: dict | None = None,
) -> None:
    """Write a structured, one-line JSON log entry for an agent event.

    event is one of: "started", "completed", "failed"
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "agent": agent,
        "event": event,
        "detail": detail or {},
    }
    logger.info(json.dumps(entry))


if __name__ == "__main__":
    log = get_logger()
    log_agent_call(log, project_id="demo-123", agent="business_analyst", event="started")
    log_agent_call(
        log,
        project_id="demo-123",
        agent="business_analyst",
        event="completed",
        detail={"summary": "Classified as booking platform"},
    )
    print(f"\nLog written to {LOG_FILE}")
