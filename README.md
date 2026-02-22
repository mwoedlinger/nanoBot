# nanoBot

A minimal Telegram bot that bridges Claude Code and shell commands, letting you run
AI-assisted tasks and execute shell commands from your phone. This is an attempt at a (very) simplified version of openClaw.

## Features

- Stream Claude Code responses with live updates and tool-call notifications
- Markdown rendered natively in Telegram (bold, code blocks, tables, etc.)
- Execute shell commands; dangerous ones require explicit `/confirm`
- Session continuity: Claude resumes the same conversation across `/task` calls
- State (session ID, work dir) persists across bot restarts
- Long responses (> 6 000 chars) are sent as file attachments
- All messages from unauthorised chat IDs are silently ignored

## Setup

### 1. Create a Telegram bot

Talk to [@BotFather](https://t.me/BotFather) and create a bot. Copy the token.

### 2. Find your chat ID

Run the script without `TELEGRAM_CHAT_ID` set — it prints your chat ID when
you send the bot any message (discovery mode). Alternatively:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
# chat ID is at result[0].message.chat.id
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set environment variables

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
export TELEGRAM_CHAT_ID="123456789"
export CLAUDE_WORK_DIR="$HOME/Dev/myproject"          # optional, defaults to ~/Dev
export NANOBOT_MEMORY_DIR="$HOME/Dev/nanoBot/memory"  # optional, default to ~/.nanoBot/memory
```

### 5. Run

```bash
python task_telegram.py
```

## Commands

| Command | Description |
|---|---|
| `/task <prompt>` | Run a Claude Code prompt (continues current session) |
| `/new` | Start a fresh Claude session |
| `/shell <cmd>` | Execute a shell command |
| `/confirm` | Confirm a pending dangerous shell command |
| `/deny` | Cancel a pending dangerous shell command |
| `/cancel` | Terminate the currently running task |
| `/cd <path>` | Change working directory (clears session) |
| `/status` | Show work dir, session ID, and whether a task is running |
| `/help` | Show command listing |

Plain messages (without a `/` prefix) are forwarded directly to Claude (i.e. equivalent to `/task`).

## Running as a background service

```bash
nohup python task_telegram.py >> task_telegram.log 2>&1 &
```

For automatic startup on macOS login, create a launchd plist under
`~/Library/LaunchAgents/`.

## Project layout

```
assistant/
  bot/
    config.py       # constants, env vars, logging
    state.py        # BotState dataclass and JSON persistence
    telegram.py     # Telegram Bot API helpers
    formatting.py   # markdown → HTML, table rendering, tool notifications
    handlers.py     # Claude/shell handlers, command router, polling loop
  task_telegram.py  # entry point
  requirements.txt
```

## State & history

- `memory/state.json` — persisted work dir and session ID
- `memory/history.jsonl` — log of completed tasks (prompt, result, session ID, duration)

## Security notes

- Only the single configured `TELEGRAM_CHAT_ID` is accepted; all other senders
  are silently dropped.
- Dangerous shell patterns (`rm`, `sudo`, `dd if=`, pipe to `bash/sh`,
  `chmod 777`, `truncate`, `mkfs`, `shred`) require `/confirm` before execution.
- `/shell` runs with the same OS privileges as the Python process. Only use
  with a private, trusted chat ID.
- Claude's tool access is limited to `Read`, `Write`, `Edit`, `Bash`, `Glob`,
  `Grep`, `WebFetch`, `WebSearch`. Edit `ALLOWED_TOOLS` in `bot/config.py` to adjust.
- The Claude subprocess times out after 5 minutes; shell commands after 60 seconds.
