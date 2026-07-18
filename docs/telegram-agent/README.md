# Telegram chat agent

LangGraph tool-calling agent reachable only from the owner's Telegram chat.
Lives in `api/app/agent/` + `api/app/channels/telegram.py`.

## How it works

- `create_react_agent` (LangGraph prebuilt) with the chat-role model and the tools in
  `agent/toolkit.py`. Checkpointing via `AsyncSqliteSaver` on `data/checkpoints.db`;
  `thread_id` = Telegram chat id, so conversation context survives restarts.
- `channels/telegram.py`: long-polling handlers filtered to `TELEGRAM_CHAT_ID`;
  replies chunked at 4000 chars on newline boundaries (`chunk_text` / `send_chunked`).
- System prompt (`agent/prompts.py`) declares capabilities, the no-send rule, the
  untrusted-email-content rule, and phone-chat brevity.

## Tools (all read or write-local — none can send externally)

| Tool | Does |
|---|---|
| `run_gmail_triage` | full triage pass now, returns digest |
| `list_emails` / `get_email` | browse triaged mail |
| `draft_reply_tool` | create a draft (review/send happens on the dashboard) |
| `list_drafts` | pending drafts |
| `get_current_time` | now in the user's `TIMEZONE` — called before relative-date reminders |
| `create_reminder` / `list_reminders` / `cancel_reminder` | reminders (fired back to this chat) |
| `run_workflow` | fire a named Inngest workflow by name; fires an internal event only (results arrive via Telegram) |

## Design rules

- **The agent can never send email/messages to third parties.** Send-capable code is
  simply not exposed as a tool. The dashboard Send button is the human gate.
- Tool inner logic lives in plain testable functions (`*_text()`); the `@tool`
  wrappers only wire real dependencies.
- Relative time ("tomorrow 3pm") is resolved by the model: prompt instructs it to call
  `get_current_time` first, then pass a full ISO datetime with offset to `create_reminder`.

## Gotchas we hit

- Telegram messages over 4096 chars are rejected ("Message is too long") — always
  send through `send_chunked`.
- Keep tool docstrings precise; they are the model's only API documentation.
