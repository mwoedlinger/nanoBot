"""Bot state: in-memory dataclass and JSON persistence."""

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field

from .config import STATE_FILE, log


@dataclass
class BotState:
    work_dir: str
    session_id: str | None = None
    active_proc: subprocess.Popen | None = None
    task_start: float | None = None
    pending_shell: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


state = BotState(work_dir=os.environ.get("CLAUDE_WORK_DIR", os.path.expanduser("~/Dev")))


def load_state() -> None:
    """Load persisted work_dir and session_id from disk."""
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text())
        state.session_id = data.get("session_id")
        if "work_dir" in data:
            state.work_dir = data["work_dir"]
        sid = f"{state.session_id[:12]}..." if state.session_id else "None"
        log.info(f"Loaded state: work_dir={state.work_dir}, session={sid}")
    except Exception as e:
        log.warning(f"Could not load state: {e}")


def save_state() -> None:
    """Persist work_dir and session_id to disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "session_id": state.session_id,
            "work_dir": state.work_dir,
        }))
    except Exception as e:
        log.warning(f"Could not save state: {e}")
