"""
Logging setup — every agent call gets logged as structured JSON lines to
logs/agent_activity.log. Deterministic logic, no AI involved.
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
        return logger

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    return logger


def log_agent_call(logger, project_id: str, agent: str, event: str, detail: dict | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "agent": agent,
        "event": event,
        "detail": detail or {},
    }
    logger.info(json.dumps(entry))
