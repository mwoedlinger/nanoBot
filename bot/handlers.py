"""Bot handlers: Claude, shell, command routing, polling loop."""

import json
import os
import subprocess
import threading
import time

from .config import (
    ALLOWED_CHAT_ID,
    BANNER,
    ALLOWED_TOOLS,
    DANGER_PATTERN,
    HELP_TEXT,
    HISTORY_FILE,
    RESULT_FILE_THRESHOLD,
    log,
)
from .formatting import format_tool_notification, md_to_html
from .state import load_state, save_state, state
from .telegram import (
    edit_message,
    get_updates,
    send_document,
    send_message,
    send_message_ret_id,
    send_preformatted,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_dangerous(cmd: str) -> bool:
    return bool(DANGER_PATTERN.search(cmd))


def log_history(prompt: str, result: str, session_id: str | None, duration_s: float) -> None:
    """Append a completed task record to the JSONL history file."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": prompt,
        "result": result,
        "session_id": session_id,
        "work_dir": state.work_dir,
        "duration_s": round(duration_s, 1),
    }
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning(f"log_history error: {e}")


# ---------------------------------------------------------------------------
# Claude handler
# ---------------------------------------------------------------------------

def handle_claude(chat_id: int, prompt: str) -> str:
    """Stream a prompt through Claude Code, sending live updates to Telegram.

    Returns "" — all messages are sent directly; the caller sends nothing.
    """
    with state.lock:
        if state.active_proc is not None:
            return "A task is already running. Use /cancel to stop it."

        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--allowedTools", ",".join(ALLOWED_TOOLS),
        ]
        if state.session_id:
            cmd += ["--resume", state.session_id]
            log.info(f"Resuming session {state.session_id[:12]}...")
        else:
            log.info("Starting new Claude session")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=state.work_dir,
            )
        except FileNotFoundError:
            return "Error: `claude` CLI not found in PATH."

        state.active_proc = proc
        state.task_start = time.monotonic()

    # Send the "⏳ Running..." placeholder only if the task takes more than 2 s.
    # For fast responses msg_id stays None and the result is sent directly.
    task_start = time.monotonic()
    msg_id: int | None = None
    task_done = threading.Event()

    def _deferred_placeholder() -> None:
        nonlocal msg_id
        if not task_done.wait(timeout=2.0):
            msg_id = send_message_ret_id(chat_id, "⏳ Running...")

    threading.Thread(target=_deferred_placeholder, daemon=True).start()

    accumulated_text = ""
    final_result = ""
    timed_out = False
    last_edit = 0.0
    stderr_buf: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_buf.append(line.rstrip())

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        while True:
            if time.monotonic() - task_start > 300:
                proc.terminate()
                timed_out = True
                break

            raw = proc.stdout.readline()
            if not raw:
                break  # EOF — process ended or was cancelled

            raw = raw.strip()
            if not raw:
                continue

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "assistant":
                for block in event.get("message", {}).get("content", []):
                    btype = block.get("type")
                    if btype == "text":
                        chunk = block.get("text", "")
                        accumulated_text += chunk
                        for ln in chunk.splitlines():
                            log.info(f"  {ln}")
                        now = time.monotonic()
                        if msg_id and now - last_edit >= 2.0 and accumulated_text:
                            edit_message(chat_id, msg_id, accumulated_text)
                            last_edit = now
                    elif btype == "tool_use":
                        notif = format_tool_notification(block.get("name", ""), block.get("input", {}))
                        log.info(f"  {notif}")
                        send_message(chat_id, notif)

            elif event_type == "result":
                final_result = event.get("result", "") or accumulated_text or "(no output)"
                new_session = event.get("session_id")
                duration_ms = event.get("duration_ms", 0)
                if new_session and new_session != state.session_id:
                    with state.lock:
                        state.session_id = new_session
                    save_state()
                    log.info(f"Session updated: {new_session[:12]}...")
                log.info(f"Claude done in {duration_ms / 1000:.1f}s ({len(final_result)} chars)")
                log_history(prompt, final_result, state.session_id, duration_ms / 1000)
                break

    finally:
        task_done.set()
        proc.wait()
        stderr_thread.join(timeout=2)
        with state.lock:
            state.active_proc = None
            state.task_start = None

    def _update_or_send(text: str, parse_mode: str = "") -> None:
        """Edit the placeholder if it exists, otherwise send a new message."""
        if msg_id:
            edit_message(chat_id, msg_id, text, parse_mode=parse_mode)
        else:
            if parse_mode:
                send_message(chat_id, text)  # already HTML from md_to_html
            else:
                send_message(chat_id, text)

    if timed_out:
        _update_or_send("⏱️ Timed out after 5 minutes.")
        return ""

    if not final_result:
        stderr_text = "\n".join(stderr_buf).strip()
        if proc.returncode != 0 and stderr_text:
            msg = f"❌ Error (exit {proc.returncode}):\n{stderr_text[:500]}"
            log.error(f"claude stderr: {stderr_text[:500]}")
        else:
            msg = "⚠️ Task interrupted."
        _update_or_send(msg)
        return ""

    if len(final_result) > RESULT_FILE_THRESHOLD:
        _update_or_send("✅ Done (full response attached)")
        send_document(chat_id, final_result, "result.txt")
    else:
        _update_or_send(md_to_html(final_result), parse_mode="HTML")

    return ""


# ---------------------------------------------------------------------------
# Shell handler
# ---------------------------------------------------------------------------

def handle_shell(chat_id: int, cmd: str, confirmed: bool = False) -> str:
    """Execute a shell command and send its output as a preformatted block.

    Dangerous commands require confirmed=True (set via the /confirm flow).
    Returns "" when output is sent directly; returns a string for short replies.
    """
    if not confirmed and is_dangerous(cmd):
        with state.lock:
            state.pending_shell = cmd
        return (
            f"⚠️ Dangerous command detected:\n`{cmd}`\n\n"
            "Send /confirm to execute or /deny to cancel."
        )

    with state.lock:
        if state.active_proc is not None:
            return "A task is already running. Use /cancel to stop it."
        try:
            proc = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=state.work_dir,
            )
        except Exception as e:
            return f"Error: {e}"
        state.active_proc = proc

    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.terminate()
        with state.lock:
            state.active_proc = None
        return "Timed out after 60 seconds."

    with state.lock:
        state.active_proc = None

    output = stdout.strip()
    if stderr.strip():
        output = (output + "\n" + stderr.strip()).strip()
    output = output or "(no output)"

    lines = output.splitlines()
    if len(lines) > 10:
        log.info(f"  ... ({len(lines) - 10} lines omitted)")
    for ln in lines[-10:]:
        log.info(f"  {ln}")

    send_preformatted(chat_id, output)
    return ""


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

def handle(chat_id: int, text: str) -> str:
    """Route an incoming message to the appropriate handler."""
    if text.startswith("/task "):
        return handle_claude(chat_id, text[6:].strip())
    if text == "/task":
        return "Usage: /task <prompt>"

    if text.startswith("/shell "):
        return handle_shell(chat_id, text[7:].strip())
    if text == "/shell":
        return "Usage: /shell <command>"

    if text == "/confirm":
        with state.lock:
            cmd = state.pending_shell
            state.pending_shell = None
        if not cmd:
            return "No pending command to confirm."
        return handle_shell(chat_id, cmd, confirmed=True)

    if text == "/deny":
        with state.lock:
            had_pending = state.pending_shell is not None
            state.pending_shell = None
        return "Command cancelled." if had_pending else "No pending command."

    if text == "/new":
        with state.lock:
            state.session_id = None
        save_state()
        return "Session cleared. Next /task starts a fresh conversation."

    if text == "/cancel":
        with state.lock:
            proc = state.active_proc
        if proc is None:
            return "No task is currently running."
        proc.terminate()
        return "Cancelled."

    if text.startswith("/cd "):
        raw = os.path.expanduser(text[4:].strip())
        path = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(state.work_dir, raw))
        if not os.path.isdir(path):
            return f"Not a directory: {path}"
        with state.lock:
            state.work_dir = path
            state.session_id = None
        save_state()
        return f"Work dir: {path}\nSession cleared."
    if text == "/cd":
        return "Usage: /cd <path>"

    if text == "/status":
        with state.lock:
            sid = state.session_id
            wdir = state.work_dir
            running = state.active_proc is not None
            t_start = state.task_start
        session_str = f"{sid[:16]}..." if sid else "None"
        elapsed = f" ({int(time.monotonic() - t_start)}s elapsed)" if running and t_start else ""
        return f"Work dir: {wdir}\nSession: {session_str}\nRunning: {('Yes' + elapsed) if running else 'No'}"

    if text in ("/help", "/start"):
        return HELP_TEXT

    # Plain text → Claude
    return handle_claude(chat_id, text)


def dispatch(chat_id: int, text: str) -> None:
    """Call handle() and send the reply only if non-empty."""
    reply = handle(chat_id, text)
    if reply:
        send_message(chat_id, reply)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the bot and poll for messages indefinitely."""
    print(BANNER)

    if ALLOWED_CHAT_ID is None:
        log.info("TELEGRAM_CHAT_ID not set — running in discovery mode.")
        log.info("Send any message to your bot and your chat ID will be printed here.")
        offset = None
        while True:
            for update in get_updates(offset):
                offset = update["update_id"] + 1
                chat_id = update.get("message", {}).get("chat", {}).get("id")
                if chat_id:
                    log.info(f"Your chat ID: {chat_id}")
                    log.info(f"Set it with: export TELEGRAM_CHAT_ID={chat_id}")
                    return
        return

    load_state()
    sid = f"{state.session_id[:12]}..." if state.session_id else "None"
    log.info(f"Bot started. Work dir: {state.work_dir}, Session: {sid}")

    offset = None
    while True:
        for update in get_updates(offset):
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "").strip()
            if chat_id != ALLOWED_CHAT_ID:
                if chat_id:
                    log.warning(f"Ignored message from unauthorized chat_id={chat_id}")
                continue
            if not text:
                continue
            log.info(f"[{chat_id}] {text!r}")
            threading.Thread(target=dispatch, args=(chat_id, text), daemon=True).start()
