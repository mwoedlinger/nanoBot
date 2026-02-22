"""Configuration, constants, and logging setup."""

import logging
import os
import re
from pathlib import Path

# --- Telegram ---
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"]) if "TELEGRAM_CHAT_ID" in os.environ else None
API = f"https://api.telegram.org/bot{TOKEN}"

# --- Paths ---
MEMORY_DIR = Path(os.environ.get("NANOBOT_MEMORY_DIR", Path.home() / ".nanoBot" / "memory"))
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = MEMORY_DIR / "state.json"
HISTORY_FILE = MEMORY_DIR / "history.jsonl"

# --- Limits ---
RESULT_FILE_THRESHOLD = 6000  # chars; larger results are sent as file attachments

# --- Claude ---
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]

TOOL_EMOJI: dict[str, str] = {
    "Bash": "🔧", "Read": "📖", "Write": "✍️", "Edit": "✏️",
    "Glob": "🔍", "Grep": "🔍", "WebFetch": "🌐", "WebSearch": "🌐",
}

# --- Shell safety ---
DANGER_PATTERN = re.compile(
    r"(rm\s|sudo\s|dd\s+if=|\|\s*(bash|sh)\b|chmod.*777|truncate\s|mkfs\b|shred\s)"
)

# --- Help text ---
HELP_TEXT = """\
Commands:
  /task <prompt>  — run Claude Code (continues current session)
  /new            — start a fresh Claude session
  /shell <cmd>    — run a shell command
  /confirm        — confirm a dangerous shell command
  /deny           — cancel a pending shell command
  /cancel         — terminate the running task
  /cd <path>      — change working directory (clears session)
  /status         — show current state
  /help           — show this message"""

# --- Banner ---
BANNER = r"""
 _ __   __ _ _ __   ___  | __ )  ___ | |_
| '_ \ / _` | '_ \ / _ \ |  _ \ / _ \| __|
| | | | (_| | | | | (_) || |_) | (_) | |_
|_| |_|\__,_|_| |_|\___/ |____/ \___/ \__|
─────────────────────────────────────────
  Telegram · Claude Code  ·  /help to start
"""

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")
