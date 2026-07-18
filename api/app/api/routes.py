"""JSON API for the dashboard: emails, drafts, and the human-gated send flow."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.store.db import Draft, DraftStatus, Email, EmailStatus, get_session

logger = logging.getLogger(__name__)


# --- reply sender dependency (overridable in tests) ---

def get_gmail_account(account_name: str):
    from app.config import get_settings
    from app.tools.gmail.client import load_accounts

    accounts = {a.account: a for a in load_accounts(get_settings())}
    account = accounts.get(account_name)
    if account is None:
        raise HTTPException(502, f"No Gmail credentials for account {account_name!r}")
    return account


# --- serializers ---

def _email_json(e: Email, include_body: bool = False) -> dict:
    data = {
        "id": e.id,
        "account": e.account,
        "sender": e.sender,
        "subject": e.subject,
        "snippet": e.snippet,
        "category": e.category,
        "status": e.status,
        "suspicious": e.suspicious,
        "urgency": e.urgency,
        "reason": e.reason,
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
    if include_body:
        data["body"] = e.body
    return data


def _draft_json(d: Draft, e: Email | None, include_body: bool = False) -> dict:
    from app.config import get_settings
    import json
    try:
        keys = json.loads(d.attachments)
    except Exception:
        keys = []
    
    settings = get_settings()
    att_meta = {m.key: m for m in settings.attachment_list}
    parsed_attachments = []
    for k in keys:
        if k in att_meta:
            parsed_attachments.append({"key": k, "label": att_meta[k].label})

    data = {
        "id": d.id,
        "kind": d.kind,
        "body": d.body,
        "subject": d.subject,
        "to_addr": d.to_addr,
        "account": d.account,
        "attachments": parsed_attachments,
        "gmail_draft_id": d.gmail_draft_id,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in d.messages
        ],
        "rotom_footer_default": bool(_resolve_footer_url(settings, None)),
    }
    if e:
        data["email"] = _email_json(e, include_body=include_body)
    else:
        data["email"] = None
    return data


def _resolve_footer_url(settings, rotom_footer: bool | None) -> str:
    """Footer link to apply for this send/save. Empty string => no footer.

    The per-request flag (the dashboard switch) wins; when omitted, fall back to
    the global default. A footer needs a configured URL to render at all.
    """
    use_footer = rotom_footer if rotom_footer is not None else settings.email_footer_enabled
    return settings.email_footer_url if (use_footer and settings.email_footer_url) else ""


class FooterOption(BaseModel):
    rotom_footer: bool | None = None


class DraftUpdate(BaseModel):
    body: str | None = None
    subject: str | None = None
    to_addr: str | None = None
    account: str | None = None
    attachments: list[str] | None = None


def create_app(api_token: str) -> FastAPI:
    app = FastAPI(title="rotom api")

    async def require_auth(request: Request) -> None:
        import hmac

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        # Reject if: wrong scheme, no configured token (empty secret = fail-open),
        # or mismatch. Constant-time compare avoids a token-recovery timing channel.
        if scheme != "Bearer" or not api_token or not hmac.compare_digest(token, api_token):
            raise HTTPException(401, "Invalid or missing bearer token")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    def _parse_date(value: str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise HTTPException(422, f"Invalid date {value!r}; expected YYYY-MM-DD")

    @app.get("/api/emails/accounts", dependencies=[Depends(require_auth)])
    async def list_accounts() -> list[str]:
        with get_session() as s:
            rows = s.query(Email.account).distinct().order_by(Email.account).all()
            return [r[0] for r in rows]

    @app.get("/api/emails", dependencies=[Depends(require_auth)])
    async def list_emails(
        category: str = "",
        account: str = "",
        status: str = "",
        suspicious: str = "",
        urgency: str = "",
        received_from: str = "",
        received_to: str = "",
        triaged_from: str = "",
        triaged_to: str = "",
        limit: int = 100,
    ) -> list[dict]:
        with get_session() as s:
            q = s.query(Email).order_by(Email.created_at.desc())
            if category:
                # comma-separated list, e.g. critical,needs_reply ("action required")
                q = q.filter(Email.category.in_([c.strip() for c in category.split(",") if c.strip()]))
            if account:
                q = q.filter(Email.account.in_([a.strip() for a in account.split(",") if a.strip()]))
            if status:
                q = q.filter(Email.status.in_([v.strip() for v in status.split(",") if v.strip()]))
            if suspicious.lower() == "true":
                q = q.filter(Email.suspicious.is_(True))
            elif suspicious.lower() == "false":
                q = q.filter(Email.suspicious.is_(False))
            if urgency:
                levels = [int(u) for u in urgency.split(",") if u.strip().isdigit()]
                if levels:
                    q = q.filter(Email.urgency.in_(levels))
            # email date (received_at) — "to" is inclusive of the whole day
            if received_from:
                q = q.filter(Email.received_at >= _parse_date(received_from))
            if received_to:
                q = q.filter(Email.received_at < _parse_date(received_to) + timedelta(days=1))
            # triage date (created_at)
            if triaged_from:
                q = q.filter(Email.created_at >= _parse_date(triaged_from))
            if triaged_to:
                q = q.filter(Email.created_at < _parse_date(triaged_to) + timedelta(days=1))
            return [_email_json(e) for e in q.limit(limit).all()]

    @app.get("/api/drafts", dependencies=[Depends(require_auth)])
    async def list_drafts(status: str = DraftStatus.PENDING) -> list[dict]:
        with get_session() as s:
            rows = (
                s.query(Draft, Email)
                .outerjoin(Email, Draft.email_id == Email.id)
                .filter(Draft.status == status)
                .order_by(Draft.created_at.desc())
                .all()
            )
            return [_draft_json(d, e) for d, e in rows]

    @app.get("/api/emails/{email_id}", dependencies=[Depends(require_auth)])
    async def get_email(email_id: int) -> dict:
        with get_session() as s:
            e = s.get(Email, email_id)
            if e is None:
                raise HTTPException(404, f"Email {email_id} not found")
            drafts = s.query(Draft).filter(Draft.email_id == email_id).order_by(Draft.created_at.desc()).all()
            data = _email_json(e, include_body=True)
            data["drafts"] = [
                {"id": d.id, "body": d.body, "status": d.status,
                 "created_at": d.created_at.isoformat() if d.created_at else None}
                for d in drafts
            ]
            return data

    class EmailStatusUpdate(BaseModel):
        status: str

    class BulkEmailStatusUpdate(BaseModel):
        ids: list[int]
        status: str

    @app.post("/api/emails/status", dependencies=[Depends(require_auth)])
    async def bulk_update_email_status(update: BulkEmailStatusUpdate) -> dict:
        if update.status not in {s.value for s in EmailStatus}:
            raise HTTPException(422, f"Invalid status {update.status!r}")
        with get_session() as s:
            updated = (
                s.query(Email)
                .filter(Email.id.in_(update.ids))
                .update({Email.status: update.status}, synchronize_session=False)
            )
            return {"updated": updated, "status": update.status}

    @app.patch("/api/emails/{email_id}", dependencies=[Depends(require_auth)])
    async def update_email_status(email_id: int, update: EmailStatusUpdate) -> dict:
        if update.status not in {s.value for s in EmailStatus}:
            raise HTTPException(422, f"Invalid status {update.status!r}")
        with get_session() as s:
            e = s.get(Email, email_id)
            if e is None:
                raise HTTPException(404, f"Email {email_id} not found")
            e.status = update.status
            return _email_json(e)

    # NOTE: sync `def` (not async) on purpose — these do blocking LLM/Gmail I/O.
    # FastAPI runs sync path operations in its worker threadpool, so they don't block
    # the shared event loop (which also runs the Telegram bot + scheduler).
    @app.post("/api/emails/{email_id}/draft", dependencies=[Depends(require_auth)])
    def regenerate_draft(email_id: int) -> dict:
        """(Re)generate the reply draft for an email. Replaces the pending draft if one exists."""
        from app.llm.provider import get_chat_model
        from app.tools.drafts.composer import ComposerContext, compose
        from app.config import get_settings
        from app.store.db import DraftKind, DraftMessage

        with get_session() as s:
            e = s.get(Email, email_id)
            if e is None:
                raise HTTPException(404, f"Email {email_id} not found")
            email_dict = {"sender": e.sender, "subject": e.subject,
                          "body": e.body or e.snippet, "snippet": e.snippet}

            pending = (
                s.query(Draft)
                .filter(Draft.email_id == email_id, Draft.status == DraftStatus.PENDING)
                .first()
            )
            if pending:
                draft = pending
                # Clear chat history for full regenerate
                s.query(DraftMessage).filter(DraftMessage.draft_id == draft.id).delete()
            else:
                draft = Draft(email_id=email_id, kind=DraftKind.REPLY)
                s.add(draft)
            
            s.flush()
            settings = get_settings()
            ctx = ComposerContext(
                kind=DraftKind.REPLY,
                new_message="Generate draft",
                source_email=email_dict,
                identity=type("Identity", (), {"name": settings.user_name, "signature": settings.user_signature})(),
                soul=_read_soul(settings.soul_file),
            )
            
            from app.observability.sink import record_run

            try:
                with record_run("draft_generation", source="manual") as run:
                    res = compose(ctx, get_chat_model("draft"))
                    draft.body = res.body
                    draft.messages.append(DraftMessage(draft_id=draft.id, role="user", content="Generate draft"))
                    draft.messages.append(DraftMessage(draft_id=draft.id, role="assistant", content=res.note))
                    s.flush()
                    run.summary = "Draft regenerated"
                    return _draft_json(draft, e, include_body=True)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"Error generating draft: {exc}")

    def _read_soul(path: str) -> str:
        if not path: return ""
        import os
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f: return f.read().strip()
            except Exception: pass
        return ""

    def _get_draft_or_404(s, draft_id: int) -> tuple[Draft, Email | None]:
        draft = s.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(404, f"Draft {draft_id} not found")
        email = s.get(Email, draft.email_id) if draft.email_id else None
        return draft, email

    class DraftCreate(BaseModel):
        kind: str

    class MessageCreate(BaseModel):
        content: str

    @app.post("/api/drafts", dependencies=[Depends(require_auth)])
    async def create_draft(payload: DraftCreate) -> dict:
        from app.config import get_settings
        from app.store.db import DraftKind

        with get_session() as s:
            draft = Draft(
                kind=payload.kind,
                account=get_settings().outreach_account_name if payload.kind == DraftKind.OUTREACH else None,
            )
            s.add(draft)
            s.flush()
            return _draft_json(draft, None)

    @app.post("/api/drafts/{draft_id}/messages", dependencies=[Depends(require_auth)])
    def post_draft_message(draft_id: int, payload: MessageCreate) -> dict:  # sync: blocking LLM I/O
        from app.llm.provider import get_chat_model
        from app.tools.drafts.composer import ComposerContext, compose
        from app.config import get_settings
        from app.store.db import DraftMessage, DraftKind
        import json

        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            if draft.status != DraftStatus.PENDING:
                raise HTTPException(409, f"Draft is {draft.status}")

            msg_content = payload.content
            draft.messages.append(DraftMessage(draft_id=draft_id, role="user", content=msg_content))
            s.flush()

            settings = get_settings()
            history = [(m.role, m.content) for m in draft.messages[:-1]]
            email_dict = None
            if email:
                email_dict = {"sender": email.sender, "subject": email.subject, "body": email.body or email.snippet, "snippet": email.snippet}
            
            try:
                sel_keys = json.loads(draft.attachments)
            except Exception:
                sel_keys = []
            
            att_metas = [m for m in settings.attachment_list if m.key in set(sel_keys)]

            ctx = ComposerContext(
                kind=draft.kind,
                new_message=msg_content,
                source_email=email_dict,
                history=history,
                identity=type("Identity", (), {"name": settings.user_name, "signature": settings.user_signature})(),
                attachments=att_metas,
                soul=_read_soul(settings.soul_file),
            )

            # Interactive chat is not a tracked "run": its token usage records as
            # adhoc and its logs flow to the global log stream. A compose failure
            # surfaces inline in the chat thread rather than as a 500.
            try:
                res = compose(ctx, get_chat_model("draft"))
                draft.body = res.body
                if draft.kind == DraftKind.OUTREACH:
                    if res.subject is not None:
                        draft.subject = res.subject
                    if res.to_addr is not None:
                        draft.to_addr = res.to_addr
                note = res.note or "Updated draft"
            except Exception as exc:
                note = f"Error generating draft: {exc}"

            draft.messages.append(DraftMessage(draft_id=draft_id, role="assistant", content=note))
            s.flush()
            return _draft_json(draft, email, include_body=True)

    @app.get("/api/attachments", dependencies=[Depends(require_auth)])
    async def get_attachments() -> list[dict]:
        from app.config import get_settings
        return [{"key": m.key, "label": m.label} for m in get_settings().attachment_list]

    @app.get("/api/drafts/{draft_id}", dependencies=[Depends(require_auth)])
    async def get_draft(draft_id: int) -> dict:
        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            return _draft_json(draft, email, include_body=True)

    @app.patch("/api/drafts/{draft_id}", dependencies=[Depends(require_auth)])
    async def update_draft(draft_id: int, update: DraftUpdate) -> dict:
        import json
        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            if draft.status != DraftStatus.PENDING:
                raise HTTPException(409, f"Draft is {draft.status}, not editable")
            if update.body is not None:
                draft.body = update.body
            if update.subject is not None:
                draft.subject = update.subject
            # Store NULL, never "" — NULL is the single "unset" sentinel
            # (reply drafts derive recipient/account from the source email).
            if update.to_addr is not None:
                draft.to_addr = update.to_addr.strip() or None
            if update.account is not None:
                draft.account = update.account.strip() or None
            if update.attachments is not None:
                draft.attachments = json.dumps(update.attachments)
            s.flush()
            return _draft_json(draft, email)

    @app.post("/api/drafts/{draft_id}/save-to-gmail", dependencies=[Depends(require_auth)])
    def save_to_gmail(draft_id: int, opts: FooterOption = FooterOption()) -> dict:  # sync: blocking Gmail I/O
        from app.config import get_settings, resolve_attachments
        import json
        from googleapiclient.errors import HttpError
        
        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            if draft.status != DraftStatus.PENDING:
                raise HTTPException(409, f"Draft is {draft.status}")
            
            try:
                sel_keys = json.loads(draft.attachments)
            except Exception:
                sel_keys = []
                
            try:
                paths = resolve_attachments(sel_keys, get_settings().attachment_list)
            except (FileNotFoundError, KeyError) as e:
                raise HTTPException(422, str(e))

            account_name = draft.account or (email.account if email else "")
            account = get_gmail_account(account_name)

            to_addr = draft.to_addr or (email.sender if email else "")
            subject = draft.subject or (email.subject if email else "")
            thread_id = email.thread_id if email else None
            in_reply_to = email.rfc_message_id if email else ""
            references = email.references if email else ""

            footer_url = _resolve_footer_url(get_settings(), opts.rotom_footer)

            try:
                res = account.create_gmail_draft(
                    to=to_addr,
                    subject=subject,
                    body=draft.body,
                    attachments=paths,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    references=references,
                    gmail_draft_id=draft.gmail_draft_id,
                    footer_url=footer_url,
                )
            except HttpError as e:
                if e.resp.status == 403:
                    raise HTTPException(409, "re-run auth_setup to grant gmail.compose")
                raise

            draft.gmail_draft_id = res["id"]
            s.flush()
            return _draft_json(draft, email)

    @app.post("/api/drafts/{draft_id}/send", dependencies=[Depends(require_auth)])
    def send_draft(draft_id: int, opts: FooterOption = FooterOption()) -> dict:  # sync: blocking Gmail I/O
        from app.config import get_settings, resolve_attachments
        import json
        from app.store.db import DraftKind

        # Phase 1: validate + claim the draft (PENDING -> SENDING) and gather all send
        # params, in one committed transaction. Claiming BEFORE the irreversible Gmail
        # send is the at-most-once guard: if the post-send commit later fails (or the
        # process dies), the draft is SENDING (not PENDING) so it can never be re-sent.
        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            if draft.status != DraftStatus.PENDING:
                raise HTTPException(409, f"Draft is {draft.status}, cannot send")

            to_addr = draft.to_addr or (email.sender if email else "")
            if draft.kind == DraftKind.OUTREACH and not to_addr:
                raise HTTPException(422, "Missing to_addr for outreach")

            try:
                sel_keys = json.loads(draft.attachments)
            except Exception:
                sel_keys = []
            try:
                paths = resolve_attachments(sel_keys, get_settings().attachment_list)
            except (FileNotFoundError, KeyError) as e:
                raise HTTPException(422, str(e))

            account_name = draft.account or (email.account if email else "")
            send_args = dict(
                to=to_addr,
                subject=draft.subject or (email.subject if email else ""),
                body=draft.body,
                attachments=paths,
                thread_id=email.thread_id if email else None,
                in_reply_to=email.rfc_message_id if email else "",
                references=email.references if email else "",
                footer_url=_resolve_footer_url(get_settings(), opts.rotom_footer),
            )
            gmail_draft_id = draft.gmail_draft_id
            draft.status = DraftStatus.SENDING  # committed on block exit

        # Phase 2: the actual send, outside any DB transaction.
        account = get_gmail_account(account_name)
        try:
            account.send_message(**send_args)
        except HTTPException:
            raise
        except Exception as exc:
            # Send failed → return the draft to PENDING so the user can retry.
            logger.warning("Gmail send failed for draft %s: %s", draft_id, exc)
            with get_session() as s:
                d = s.get(Draft, draft_id)
                if d is not None and d.status == DraftStatus.SENDING:
                    d.status = DraftStatus.PENDING
            raise HTTPException(502, "Gmail send failed; draft returned to pending — you can retry.")

        # Phase 3: record the send. If this commit fails the email is already sent and
        # the draft stays SENDING — never re-sendable — which is the desired outcome.
        if gmail_draft_id:
            try:
                account.delete_gmail_draft(gmail_draft_id)
            except Exception as e:
                logger.warning(f"Failed to delete gmail draft {gmail_draft_id}: {e}")

        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            draft.status = DraftStatus.SENT
            draft.sent_at = datetime.now(timezone.utc)
            return _draft_json(draft, email)

    @app.post("/api/drafts/{draft_id}/discard", dependencies=[Depends(require_auth)])
    async def discard_draft(draft_id: int) -> dict:
        with get_session() as s:
            draft, email = _get_draft_or_404(s, draft_id)
            if draft.status != DraftStatus.PENDING:
                raise HTTPException(409, f"Draft is {draft.status}, cannot discard")
            draft.status = DraftStatus.DISCARDED
            return _draft_json(draft, email)

    # --- reminders ---

    class ReminderCreate(BaseModel):
        text: str
        fire_at: str  # ISO 8601 with utc offset
        recurrence_cron: str = ""

    class ReminderParse(BaseModel):
        message: str

    @app.get("/api/reminders", dependencies=[Depends(require_auth)])
    async def list_reminders(status: str = "pending") -> list[dict]:
        from app.tools.reminders.service import list_reminders as list_rem, reminder_json

        return [reminder_json(r) for r in list_rem(status=status)]

    @app.post("/api/reminders", dependencies=[Depends(require_auth)])
    async def create_reminder(payload: ReminderCreate) -> dict:
        from app.tools.reminders.service import create_reminder as create, reminder_json

        try:
            fire_at = datetime.fromisoformat(payload.fire_at)
            if fire_at.tzinfo is None:
                raise ValueError("fire_at must include a utc offset")
            r = create(payload.text, fire_at, payload.recurrence_cron)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return reminder_json(r)

    @app.post("/api/reminders/parse", dependencies=[Depends(require_auth)])
    async def parse_reminder_route(payload: ReminderParse) -> dict:
        """NL → structured reminder proposal (NOT created — the UI confirms first)."""
        import asyncio

        from app.config import get_settings
        from app.llm.provider import get_chat_model
        from app.tools.reminders.parser import parse_reminder

        if not payload.message.strip():
            raise HTTPException(422, "Empty message")
        settings = get_settings()
        try:
            proposal = await asyncio.to_thread(
                parse_reminder, payload.message, get_chat_model("chat", settings), settings.timezone
            )
        except ValueError as exc:
            raise HTTPException(422, f"Could not understand that reminder: {exc}")
        return proposal.model_dump()

    @app.delete("/api/reminders/{reminder_id}", dependencies=[Depends(require_auth)])
    async def cancel_reminder_route(reminder_id: int) -> dict:
        from app.tools.reminders.service import cancel_reminder

        try:
            ok = cancel_reminder(reminder_id)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        if not ok:
            raise HTTPException(404, f"Reminder {reminder_id} not found or not pending")
        return {"cancelled": True, "id": reminder_id}

    class SoulUpdate(BaseModel):
        content: str

    @app.get("/api/soul", dependencies=[Depends(require_auth)])
    async def get_soul() -> dict:
        from app.config import get_settings
        import os
        path = get_settings().soul_file
        if not path or not os.path.isfile(path):
            return {"content": ""}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {"content": f.read()}
        except Exception:
            return {"content": ""}

    @app.put("/api/soul", dependencies=[Depends(require_auth)])
    async def update_soul(payload: SoulUpdate) -> dict:
        from app.config import get_settings
        import os
        path = get_settings().soul_file
        if not path:
            raise HTTPException(400, "SOUL_FILE is not configured in .env")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload.content)
            return {"ok": True}
        except Exception as e:
            raise HTTPException(500, f"Failed to write SOUL_FILE: {e}")

    def _safe_obs_read(call, default, what: str):
        """Run an observability read, degrading to `default` (not a 500) if the
        backend/DB is unavailable. The dashboard stays usable; the failure is a
        stdout warning. Observability is best-effort on reads too."""
        try:
            return call()
        except Exception:
            logger.warning("observability read failed (%s); returning empty", what, exc_info=True)
            return default

    @app.get("/api/observability/runs", dependencies=[Depends(require_auth)])
    async def get_obs_runs(limit: int = 50, source: str = "", kind: str = ""):
        from app.observability.sink import get_query_provider
        return _safe_obs_read(
            lambda: get_query_provider().list_runs(
                limit=limit, source=source or None, kind=kind or None
            ),
            [], "runs",
        )

    @app.get("/api/observability/runs/{run_id}", dependencies=[Depends(require_auth)])
    async def get_obs_run(run_id: str):
        from app.observability.sink import get_query_provider
        run = _safe_obs_read(lambda: get_query_provider().get_run(run_id), None, "run")
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/observability/usage", dependencies=[Depends(require_auth)])
    async def get_obs_usage(days: int = 14):
        from app.observability.sink import get_query_provider
        return _safe_obs_read(
            lambda: get_query_provider().usage_by_model_day(days=days), [], "usage"
        )

    @app.get("/api/observability/logs", dependencies=[Depends(require_auth)])
    async def get_obs_logs(
        level: str = "",
        kind: str = "",
        run_id: int | None = None,
        q: str = "",
        since: str = "",
        until: str = "",
        limit: int = 100,
        before_id: int | None = None,
    ):
        from app.observability.sink import get_query_provider
        return _safe_obs_read(
            lambda: get_query_provider().list_logs(
                level=level or None,
                kind=kind or None,
                run_id=run_id,
                q=q or None,
                since=since or None,
                until=until or None,
                limit=min(limit, 500),
                before_id=before_id,
            ),
            {"logs": [], "next_before_id": None}, "logs",
        )

    @app.post("/api/triage/trigger", dependencies=[Depends(require_auth)])
    async def trigger_triage_job():
        from app.scheduler.jobs import get_scheduler, scheduled_gmail_triage_job
        from apscheduler.triggers.date import DateTrigger
        from app.store.db import utcnow
        import uuid
        
        scheduler = get_scheduler()
        if not scheduler:
            raise HTTPException(status_code=500, detail="Scheduler not running")
            
        scheduler.add_job(
            scheduled_gmail_triage_job,
            trigger=DateTrigger(run_date=utcnow()),
            kwargs={"source": "manual"},
            id=f"manual-triage-{uuid.uuid4()}",
            replace_existing=False
        )
        return {"ok": True}

    return app
