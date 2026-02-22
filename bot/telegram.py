"""Telegram Bot API helpers."""

import html
import time

import requests

from .config import API, RESULT_FILE_THRESHOLD, log


def get_updates(offset: int | None = None) -> list[dict]:
    """Fetch pending updates via long polling (30 s timeout)."""
    try:
        r = requests.get(
            f"{API}/getUpdates",
            params={"timeout": 30, "offset": offset},
            timeout=35,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        log.error(f"get_updates error: {e}")
        time.sleep(5)
        return []


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Split text into chunks ≤ limit chars, preferring newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def send_message(chat_id: int, text: str) -> None:
    """Send a plain-text message, chunking if needed."""
    for chunk in split_message(text):
        try:
            requests.post(
                f"{API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=10,
            )
        except Exception as e:
            log.error(f"send_message error: {e}")


def send_message_ret_id(chat_id: int, text: str) -> int | None:
    """Send a message and return its message_id (for later editing)."""
    try:
        r = requests.post(
            f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.error(f"send_message_ret_id error: {e}")
        return None


def edit_message(chat_id: int, message_id: int, text: str, parse_mode: str = "") -> None:
    """Edit an existing message (tail-truncated to 3900 chars).

    If parse_mode is set and Telegram rejects the HTML, retries as plain text.
    """
    if len(text) > 3900:
        text = "..." + text[-3897:]
    payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(f"{API}/editMessageText", json=payload, timeout=10)
        data = r.json()
        if not data.get("ok") and parse_mode:
            log.warning(f"edit_message HTML rejected ({data.get('description')}) — retrying as plain text")
            payload.pop("parse_mode")
            requests.post(f"{API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        log.error(f"edit_message error: {e}")


def send_preformatted(chat_id: int, text: str) -> None:
    """Send text in a monospace <pre> block, or as a file if too large."""
    if len(text) > RESULT_FILE_THRESHOLD:
        send_document(chat_id, text, "output.txt")
        return
    try:
        requests.post(
            f"{API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"<pre>{html.escape(text)}</pre>",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as e:
        log.error(f"send_preformatted error: {e}")


def send_document(chat_id: int, content: str, filename: str, caption: str = "") -> None:
    """Send a UTF-8 text file as a document attachment."""
    try:
        requests.post(
            f"{API}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (filename, content.encode("utf-8"), "text/plain")},
            timeout=30,
        )
    except Exception as e:
        log.error(f"send_document error: {e}")
