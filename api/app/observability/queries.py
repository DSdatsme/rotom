"""Dashboard read models over observability.db.

Plain SQL, SQLite-specific by design (SQL-first is the point — the same tables/views are
what you query by hand). Every function returns JSON-ready dicts; timestamps are ISO-8601
UTC with offset. Percentiles are computed in Python: SQLite has no percentile function
and single-user volumes are small.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from app.store.observability import get_obs_session

PROBLEM_STATUSES = ("failure", "degraded", "interrupted")
RUN_STATUSES = ("success", "failure", "degraded", "interrupted", "running")

_TRACE_TYPE_SQL = (
    "CASE WHEN json_extract(attributes, '$.\"rotom.run.kind\"') IS NOT NULL THEN 'run' "
    "WHEN operation = 'invoke_agent' THEN 'chat' "
    "WHEN span_kind = 'SERVER' THEN 'http' ELSE 'other' END"
)


# --- helpers -----------------------------------------------------------------

def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> str | None:
    dt = _utc(value)
    return dt.isoformat() if dt else None


def _db_ts(dt: datetime) -> str:
    """A UTC datetime in the exact text format SQLAlchemy stores (string-comparable)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _floor(dt: datetime, bucket: str) -> datetime:
    dt = dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0) if bucket == "day" else dt


def _buckets(since: datetime, now: datetime, bucket: str) -> list[datetime]:
    step = timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    out, cur = [], _floor(since, bucket)
    while cur <= now:
        out.append(cur)
        cur += step
    return out


def _pct(values: Iterable[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return round(ordered[rank - 1], 1)


def _json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _sum_cost(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals), 6) if vals else None


# --- overview ----------------------------------------------------------------

def overview(hours: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    bucket = "hour" if hours <= 48 else "day"
    params = {"since": _db_ts(since)}
    with get_obs_session() as s:
        runs = s.execute(text(
            "SELECT id, kind, source, status, started_at, finished_at, summary, error, trace_id "
            "FROM run_log WHERE started_at >= :since ORDER BY id DESC"), params).mappings().all()
        llm = s.execute(text(
            "SELECT model, duration_ms, status, input_tokens, output_tokens, cost_usd, start_time "
            "FROM span WHERE operation = 'chat' AND start_time >= :since"), params).mappings().all()
        error_logs = s.execute(text(
            "SELECT COUNT(*) FROM log_entry WHERE level IN ('ERROR', 'CRITICAL') AND ts >= :since"),
            params).scalar_one()
        recent_errors = s.execute(text(
            "SELECT id, ts, logger, msg, run_id, trace_id FROM log_entry "
            "WHERE level IN ('ERROR', 'CRITICAL') AND ts >= :since ORDER BY id DESC LIMIT 10"),
            params).mappings().all()
        last_by_kind = s.execute(text(
            "SELECT r.kind, r.id, r.status, r.started_at, r.summary FROM run_log r "
            "JOIN (SELECT kind, MAX(id) AS id FROM run_log GROUP BY kind) m ON m.id = r.id")).mappings().all()
        run_cost = dict(s.execute(text(
            "SELECT run_id, SUM(cost_usd) FROM span WHERE run_id IS NOT NULL AND operation = 'chat' "
            "AND start_time >= :since GROUP BY run_id"), params).all())

    bucket_list = _buckets(since, now, bucket)
    series = {b: {"bucket": b.isoformat(), **{st: 0 for st in RUN_STATUSES}} for b in bucket_list}
    for r in runs:
        key = _floor(_utc(r["started_at"]), bucket)
        if key in series and r["status"] in RUN_STATUSES:
            series[key][r["status"]] += 1

    cost: dict[tuple[datetime, str], dict[str, float]] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
    for c in llm:
        key = (_floor(_utc(c["start_time"]), bucket), c["model"] or "unknown")
        cost[key]["cost_usd"] += c["cost_usd"] or 0.0
        cost[key]["tokens"] += (c["input_tokens"] or 0) + (c["output_tokens"] or 0)
    cost_series = [
        {"bucket": b.isoformat(), "model": m, "cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
        for (b, m), v in sorted(cost.items())
    ]

    by_kind: dict[str, list] = defaultdict(list)
    for r in runs:
        by_kind[r["kind"]].append(r)
    last = {r["kind"]: r for r in last_by_kind}
    jobs = []
    for kind in sorted(set(by_kind) | set(last)):
        rs = by_kind.get(kind, [])
        durations = [
            (_utc(r["finished_at"]) - _utc(r["started_at"])).total_seconds() * 1000
            for r in rs if r["finished_at"]
        ]
        costs = [run_cost[r["id"]] for r in rs if run_cost.get(r["id"]) is not None]
        lr = last.get(kind)
        jobs.append({
            "kind": kind,
            "runs": len(rs),
            "success": sum(r["status"] == "success" for r in rs),
            "problems": sum(r["status"] in PROBLEM_STATUSES for r in rs),
            "p50_ms": _pct(durations, 50),
            "p95_ms": _pct(durations, 95),
            "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
            "last_run_id": lr["id"] if lr else None,
            "last_status": lr["status"] if lr else None,
            "last_started_at": _iso(lr["started_at"]) if lr else None,
            "last_summary": (lr["summary"] or "") if lr else "",
        })
    jobs.sort(key=lambda j: j["last_started_at"] or "", reverse=True)

    problems = [
        {"type": "run", "ts": _iso(r["started_at"]), "run_id": r["id"], "kind": r["kind"],
         "status": r["status"], "summary": r["summary"] or "", "error": r["error"] or "",
         "trace_id": r["trace_id"]}
        for r in runs if r["status"] in PROBLEM_STATUSES
    ][:10] + [
        {"type": "log", "ts": _iso(e["ts"]), "id": e["id"], "logger": e["logger"], "msg": e["msg"],
         "run_id": e["run_id"], "trace_id": e["trace_id"]}
        for e in recent_errors
    ]
    problems.sort(key=lambda p: p["ts"] or "", reverse=True)

    llm_durations = [c["duration_ms"] for c in llm]
    return {
        "window_hours": hours,
        "bucket": bucket,
        "buckets": [b.isoformat() for b in bucket_list],
        "kpis": {
            "runs": len(runs),
            "runs_ok": sum(r["status"] == "success" for r in runs),
            "problems": sum(r["status"] in PROBLEM_STATUSES for r in runs),
            "running": sum(r["status"] == "running" for r in runs),
            "llm_calls": len(llm),
            "llm_errors": sum(c["status"] == "ERROR" for c in llm),
            "cost_usd": round(sum(c["cost_usd"] or 0.0 for c in llm), 6),
            "input_tokens": sum(c["input_tokens"] or 0 for c in llm),
            "output_tokens": sum(c["output_tokens"] or 0 for c in llm),
            "llm_p95_ms": _pct(llm_durations, 95),
            "error_logs": error_logs,
        },
        "runs_series": list(series.values()),
        "cost_series": cost_series,
        "jobs": jobs,
        "problems": problems[:12],
    }


def empty_overview(hours: int) -> dict[str, Any]:
    return {"window_hours": hours, "bucket": "hour" if hours <= 48 else "day", "buckets": [],
            "kpis": {"runs": 0, "runs_ok": 0, "problems": 0, "running": 0, "llm_calls": 0,
                     "llm_errors": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                     "llm_p95_ms": None, "error_logs": 0},
            "runs_series": [], "cost_series": [], "jobs": [], "problems": []}


# --- traces ------------------------------------------------------------------

def traces(
    *,
    limit: int = 50,
    before: str | None = None,
    trace_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    where = ["parent_span_id IS NULL", "trace_id IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit + 1}
    if before:
        where.append("start_time < :before")
        params["before"] = _db_ts(_utc(before))
    if trace_type:
        where.append(f"{_TRACE_TYPE_SQL} = :ttype")
        params["ttype"] = trace_type
    if status == "error":
        where.append("status = 'ERROR'")
    elif status == "ok":
        where.append("status != 'ERROR'")
    if q:
        where.append("name LIKE :q")
        params["q"] = f"%{q}%"
    with get_obs_session() as s:
        roots = s.execute(text(
            f"SELECT trace_id, span_id, name, {_TRACE_TYPE_SQL} AS trace_type, start_time, duration_ms, "
            "run_id, status, json_extract(attributes, '$.\"rotom.run.status\"') AS run_status "
            f"FROM span WHERE {' AND '.join(where)} ORDER BY start_time DESC LIMIT :limit"),
            params).mappings().all()
        has_more = len(roots) > limit
        roots = roots[:limit]
        agg: dict[str, Any] = {}
        if roots:
            ids = {f"t{i}": r["trace_id"] for i, r in enumerate(roots)}
            placeholders = ",".join(f":{k}" for k in ids)
            for a in s.execute(text(
                "SELECT trace_id, COUNT(*) AS span_count, SUM(operation = 'chat') AS llm_calls, "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "SUM(cost_usd) AS cost_usd, SUM(status = 'ERROR') AS error_count "
                f"FROM span WHERE trace_id IN ({placeholders}) GROUP BY trace_id"), ids).mappings():
                agg[a["trace_id"]] = a
    out = []
    for r in roots:
        a = agg.get(r["trace_id"], {})
        out.append({
            "trace_id": r["trace_id"],
            "root_span_id": r["span_id"],
            "root_name": r["name"],
            "trace_type": r["trace_type"],
            "start_time": _iso(r["start_time"]),
            "duration_ms": r["duration_ms"],
            "run_id": r["run_id"],
            "run_status": r["run_status"],
            "status": r["status"],
            "span_count": a.get("span_count", 1),
            "llm_calls": a.get("llm_calls") or 0,
            "input_tokens": a.get("input_tokens", 0),
            "output_tokens": a.get("output_tokens", 0),
            "cost_usd": a.get("cost_usd"),
            "error_count": a.get("error_count") or 0,
        })
    return {"traces": out, "next_before": _iso(roots[-1]["start_time"]) if has_more and roots else None}


def _span_dict(r) -> dict[str, Any]:
    d = dict(r)
    d["start_time"] = _iso(d["start_time"])
    d["end_time"] = _iso(d["end_time"])
    d["attributes"] = _json(d.get("attributes"), {})
    d["events"] = _json(d.get("events"), [])
    return d


def _log_dict(r) -> dict[str, Any]:
    d = dict(r)
    d["ts"] = _iso(d["ts"])
    return d


def trace_detail(trace_id: str) -> dict[str, Any] | None:
    with get_obs_session() as s:
        spans = s.execute(text("SELECT * FROM span WHERE trace_id = :t ORDER BY start_time ASC"),
                          {"t": trace_id}).mappings().all()
        if not spans:
            return None
        logs = s.execute(text(
            "SELECT id, ts, level, logger, msg, run_id, kind, trace_id, span_id, exc_info, extra "
            "FROM log_entry WHERE trace_id = :t ORDER BY id ASC LIMIT 2000"), {"t": trace_id}).mappings().all()
        run = s.execute(text(
            "SELECT id, kind, source, status, started_at, finished_at, summary, error "
            "FROM run_log WHERE trace_id = :t ORDER BY id ASC LIMIT 1"), {"t": trace_id}).mappings().first()
    run_dict = None
    if run:
        run_dict = dict(run)
        run_dict["started_at"] = _iso(run_dict["started_at"])
        run_dict["finished_at"] = _iso(run_dict["finished_at"])
    return {"trace_id": trace_id, "spans": [_span_dict(r) for r in spans],
            "logs": [_log_dict(l) for l in logs], "run": run_dict}


# --- LLM ---------------------------------------------------------------------

def _group_stats(rows: list) -> dict[str, Any]:
    return {
        "calls": len(rows),
        "errors": sum(r["status"] == "ERROR" for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "cost_usd": _sum_cost(r["cost_usd"] for r in rows),
        "p50_ms": _pct((r["duration_ms"] for r in rows), 50),
        "p95_ms": _pct((r["duration_ms"] for r in rows), 95),
    }


def llm_stats(days: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    with get_obs_session() as s:
        rows = s.execute(text(
            "SELECT s.span_id, s.trace_id, s.run_id, r.kind AS run_kind, s.start_time, s.duration_ms, "
            "s.status, s.provider, s.model, json_extract(s.attributes, '$.\"rotom.llm.role\"') AS role, "
            "COALESCE(s.input_tokens, 0) AS input_tokens, COALESCE(s.output_tokens, 0) AS output_tokens, "
            "COALESCE(s.cache_read_tokens, 0) AS cache_read_tokens, "
            "COALESCE(s.reasoning_tokens, 0) AS reasoning_tokens, s.cost_usd "
            "FROM span s LEFT JOIN run_log r ON r.id = s.run_id "
            "WHERE s.operation = 'chat' AND s.start_time >= :since ORDER BY s.start_time DESC"),
            {"since": _db_ts(since)}).mappings().all()

    by_model: dict[tuple, list] = defaultdict(list)
    by_role: dict[str, list] = defaultdict(list)
    daily: dict[tuple, dict] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
    for r in rows:
        by_model[(r["model"] or "unknown", r["provider"])].append(r)
        by_role[r["role"] or "unknown"].append(r)
        key = (_floor(_utc(r["start_time"]), "day"), r["model"] or "unknown")
        daily[key]["cost_usd"] += r["cost_usd"] or 0.0
        daily[key]["tokens"] += r["input_tokens"] + r["output_tokens"]

    kpis = _group_stats(rows)
    kpis["cache_hit_pct"] = (
        round(kpis["cache_read_tokens"] / kpis["input_tokens"] * 100, 1) if kpis["input_tokens"] else None
    )
    recent = []
    for r in rows[:50]:
        d = dict(r)
        d["start_time"] = _iso(d["start_time"])
        recent.append(d)
    return {
        "days": days,
        "buckets": [b.isoformat() for b in _buckets(since, now, "day")],
        "kpis": kpis,
        "by_model": sorted(
            ({"model": m, "provider": p, **_group_stats(rs)} for (m, p), rs in by_model.items()),
            key=lambda x: (x["cost_usd"] or 0, x["calls"]), reverse=True),
        "by_role": sorted(
            ({"role": role, **_group_stats(rs)} for role, rs in by_role.items()),
            key=lambda x: x["calls"], reverse=True),
        "daily": [{"bucket": b.isoformat(), "model": m, "cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
                  for (b, m), v in sorted(daily.items())],
        "recent": recent,
    }


def empty_llm_stats(days: int) -> dict[str, Any]:
    zero = {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "reasoning_tokens": 0, "cost_usd": None, "p50_ms": None, "p95_ms": None, "cache_hit_pct": None}
    return {"days": days, "buckets": [], "kpis": zero, "by_model": [], "by_role": [], "daily": [], "recent": []}
