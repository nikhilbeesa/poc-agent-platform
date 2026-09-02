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
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    return logger


def log_agent_call(logger, project_id: str, agent: str, event: str, detail: dict | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id, "agent": agent, "event": event, "detail": detail or {},
    }
    logger.info(json.dumps(entry))
