from typing import Any
from sqlalchemy import select, func, text
from app.observability.events import UsageEvent, RunResult, RunStart
from app.store.observability import get_obs_session, RunLog, LLMUsage, RunStatus, LogEntry, utcnow

class SqliteSink:
    def record_usage(self, e: UsageEvent) -> None:
        with get_obs_session() as session:
            usage = LLMUsage(
                ts=e.ts,
                run_id=int(e.run_id) if e.run_id else None,
                provider=e.provider,
                model=e.model,
                role=e.role,
                input_tokens=e.input_tokens,
                output_tokens=e.output_tokens,
                # Feature B: persist latency
                latency_ms=e.latency_ms,
            )
            session.add(usage)
            session.commit()

    def start_run(self, run: RunStart) -> str:
        with get_obs_session() as session:
            row = RunLog(
                kind=run.kind,
                source=run.source,
                status=RunStatus.RUNNING,
                external_id=run.external_id,
                external_url=run.external_url,
                parent_run_id=int(run.parent_run_id) if run.parent_run_id else None,
                last_heartbeat_at=utcnow(),
            )
            session.add(row)
            session.commit()
            return str(row.id)

    def finish_run(self, run_id: str, result: RunResult) -> None:
        with get_obs_session() as session:
            run = session.get(RunLog, int(run_id))
            if run:
                run.finished_at = utcnow()
                run.status = result.status
                run.summary = result.summary
                run.error = result.error
                run.logs = result.logs
                session.commit()

    def heartbeat(self, run_id: str) -> None:
        """Bump last_heartbeat_at so the reaper knows this run is still alive."""
        with get_obs_session() as session:
            run = session.get(RunLog, int(run_id))
            if run:
                run.last_heartbeat_at = utcnow()
                session.commit()

    def reap_stale_runs(self, *, timeout_seconds: int = 300) -> int:
        """Flip zombie `running` rows to `interrupted`.

        A run is dead if it's still `running`, isn't an Inngest run (durable —
        resumes on its own), and either its last heartbeat or (absent one) its
        start time is older than `timeout_seconds`. Returns how many were reaped.
        """
        from datetime import timedelta, timezone

        def _as_utc(dt):
            # SQLite drops tzinfo on read; treat stored datetimes as UTC.
            if dt is None:
                return None
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

        cutoff = utcnow() - timedelta(seconds=timeout_seconds)
        reaped = 0
        with get_obs_session() as session:
            stmt = select(RunLog).where(
                RunLog.status == RunStatus.RUNNING,
                RunLog.source != "inngest",
            )
            for run in session.scalars(stmt).all():
                hb = _as_utc(run.last_heartbeat_at)
                started = _as_utc(run.started_at)
                dead = (hb is not None and hb < cutoff) or (
                    hb is None and started is not None and started < cutoff
                )
                if dead:
                    run.status = RunStatus.INTERRUPTED
                    run.finished_at = utcnow()
                    run.summary = run.summary or "Interrupted"
                    run.error = run.error or "Run interrupted — process exited before completion"
                    reaped += 1
            session.commit()
        return reaped

    def list_runs(
        self,
        limit: int,
        *,
        source: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_obs_session() as session:
            stmt = select(RunLog)
            if source:
                stmt = stmt.where(RunLog.source == source)
            if kind:
                stmt = stmt.where(RunLog.kind == kind)
            stmt = stmt.order_by(RunLog.id.desc()).limit(limit)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "source": r.source,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "status": r.status,
                    "summary": r.summary,
                    "external_url": r.external_url,
                    "parent_run_id": r.parent_run_id,
                }
                for r in rows
            ]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with get_obs_session() as session:
            run = session.get(RunLog, int(run_id))
            if not run:
                return None

            stmt = select(
                LLMUsage.model,
                func.sum(LLMUsage.input_tokens).label("in_tokens"),
                func.sum(LLMUsage.output_tokens).label("out_tokens"),
                func.avg(LLMUsage.latency_ms).label("avg_latency_ms"),
            ).where(LLMUsage.run_id == run.id).group_by(LLMUsage.model)

            metrics = []
            for row in session.execute(stmt):
                metrics.append({
                    "model": row.model,
                    "input_tokens": row.in_tokens,
                    "output_tokens": row.out_tokens,
                    # Feature B: per-model avg latency (rounded to int, None if no data)
                    "avg_latency_ms": int(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
                })

            # Parent breadcrumb (when nested)
            parent = None
            if run.parent_run_id is not None:
                p = session.get(RunLog, run.parent_run_id)
                if p:
                    parent = {"id": p.id, "kind": p.kind, "source": p.source}

            # Sub-runs (rows whose parent is this run)
            child_rows = session.scalars(
                select(RunLog).where(RunLog.parent_run_id == run.id).order_by(RunLog.id.asc())
            ).all()
            children = [
                {
                    "id": c.id,
                    "kind": c.kind,
                    "source": c.source,
                    "status": c.status,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                }
                for c in child_rows
            ]

            return {
                "id": run.id,
                "kind": run.kind,
                "source": run.source,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "summary": run.summary,
                "error": run.error,
                "logs": run.logs,
                "external_id": run.external_id,
                "external_url": run.external_url,
                "parent_run_id": run.parent_run_id,
                "parent": parent,
                "children": children,
                "metrics": metrics,
            }

    def usage_by_model_day(self, days: int) -> list[dict[str, Any]]:
        from datetime import datetime, timedelta, timezone
        from app.store.observability import RunLog
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with get_obs_session() as session:
            stmt = select(
                func.strftime('%Y-%m-%dT%H:%M:%SZ', func.min(LLMUsage.ts)).label("day"),
                RunLog.id.label("run_id"),
                RunLog.kind.label("purpose"),
                LLMUsage.model,
                func.sum(LLMUsage.input_tokens).label("in_tokens"),
                func.sum(LLMUsage.output_tokens).label("out_tokens"),
                func.avg(LLMUsage.latency_ms).label("avg_latency_ms"),
            ).outerjoin(RunLog, LLMUsage.run_id == RunLog.id) \
             .where(LLMUsage.ts >= cutoff).group_by(
                func.strftime('%Y-%m-%d', LLMUsage.ts),
                RunLog.id,
                RunLog.kind,
                LLMUsage.model
            ).order_by(text("day DESC, run_id DESC, model ASC"))

            results = []
            for row in session.execute(stmt):
                results.append({
                    "day": row.day,
                    "run_id": row.run_id,
                    "purpose": row.purpose,
                    "model": row.model,
                    "input_tokens": row.in_tokens,
                    "output_tokens": row.out_tokens,
                    # Feature B: avg latency for this model/day/run bucket
                    "avg_latency_ms": int(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
                })
            return results

    def list_logs(
        self,
        *,
        level: str | None = None,
        kind: str | None = None,
        run_id: int | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, Any]:
        """Newest-first, id-based cursor pagination for the Logs Explorer.

        Returns {"logs": [...], "next_before_id": <id|None>}
        - before_id: fetch rows with id < before_id (i.e. older than the cursor)
        - level: comma-separated list of level names (case-insensitive)
        - q: case-insensitive LIKE match on msg
        - since/until: ISO datetime strings filtering on ts
        """
        from datetime import datetime, timezone

        with get_obs_session() as session:
            stmt = select(LogEntry)

            if before_id is not None:
                stmt = stmt.where(LogEntry.id < before_id)

            if level:
                levels = [l.strip().upper() for l in level.split(",") if l.strip()]
                if levels:
                    stmt = stmt.where(LogEntry.level.in_(levels))

            if kind:
                stmt = stmt.where(LogEntry.kind == kind)

            if run_id is not None:
                stmt = stmt.where(LogEntry.run_id == run_id)

            if q:
                stmt = stmt.where(LogEntry.msg.ilike(f"%{q}%"))

            if since:
                try:
                    dt = datetime.fromisoformat(since)
                    stmt = stmt.where(LogEntry.ts >= dt)
                except ValueError:
                    pass

            if until:
                try:
                    dt = datetime.fromisoformat(until)
                    stmt = stmt.where(LogEntry.ts <= dt)
                except ValueError:
                    pass

            # Fetch one extra to determine if there's a next page
            stmt = stmt.order_by(LogEntry.id.desc()).limit(limit + 1)
            rows = session.scalars(stmt).all()

            has_more = len(rows) > limit
            rows = rows[:limit]

            next_before_id = rows[-1].id if has_more and rows else None

            return {
                "logs": [
                    {
                        "id": r.id,
                        "ts": r.ts.isoformat() if r.ts else None,
                        "level": r.level,
                        "logger": r.logger,
                        "msg": r.msg,
                        "run_id": r.run_id,
                        "kind": r.kind,
                        "extra": r.extra,
                    }
                    for r in rows
                ],
                "next_before_id": next_before_id,
            }
