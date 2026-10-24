# Querying rotom's telemetry

Everything is in `data/observability.db` (SQLite). `make obs-sql` opens it read-only in sqlite3
(`OBS_DB=path` overrides the default `api/data/observability.db`); `make obs-ui` opens
Datasette (read-only) at http://127.0.0.1:8001. DuckDB works too:
`duckdb -c "INSTALL sqlite; LOAD sqlite; ATTACH 'api/data/observability.db' AS obs (TYPE sqlite); SELECT * FROM obs.v_runs LIMIT 5"`.

Timestamps are UTC (`YYYY-MM-DD HH:MM:SS.ffffff`). Span attributes are JSON:
`json_extract(attributes, '$."gen_ai.tool.name"')`.

Legacy (pre-tracing) LLM rows were backfilled into `span` with `trace_id NULL` and
`rotom.legacy=true`; they show up in `v_llm_calls` / `v_runs` but not in `v_traces`.

## Tables & views

| name | one row per |
|---|---|
| `run_log` / `v_runs` | unit of work (triage, reminder, draft...); `v_runs` adds LLM calls, tokens, cost |
| `span` | OTel span (run, step, agent turn, tool call, LLM call, API request) |
| `v_traces` | trace (root span + rollups); `trace_type` is `run`, `chat`, `http` or `other`; `run_id` falls back to a run inside the trace (e.g. a draft regeneration under an `http` root) |
| `v_llm_calls` | LLM call incl. role, tokens, cost, prompt/response |
| `v_tool_calls` | agent tool call incl. arguments/result |
| `v_errors` | ERROR span or ERROR/CRITICAL log line |
| `log_entry` | log line (joins to spans by `trace_id`/`span_id`, to runs by `run_id`) |
| `obs_meta` | key/value (semconv version, backfill markers) |
| `llm_usage` | retired v1 table; no new writes |

## Recipes

What failed today, with the trace to open:

```sql
SELECT ts, source, what, substr(message, 1, 120) AS message, trace_id
FROM v_errors WHERE ts >= date('now') ORDER BY ts DESC;
```

Spend per day per model (last 14 days):

```sql
SELECT date(start_time) AS day, model, round(SUM(cost_usd), 4) AS usd, COUNT(*) AS calls
FROM v_llm_calls WHERE start_time >= date('now', '-14 days')
GROUP BY day, model ORDER BY day DESC, usd DESC;
```

Cost and duration per run kind (last 7 days):

```sql
SELECT kind, COUNT(*) AS runs, round(AVG(duration_ms)/1000, 1) AS avg_s,
       round(SUM(cost_usd), 4) AS usd, SUM(status != 'success') AS problems
FROM v_runs WHERE started_at >= date('now', '-7 days') GROUP BY kind ORDER BY usd DESC;
```

Where did the slowest triage spend its time?

```sql
WITH t AS (SELECT trace_id FROM v_runs WHERE kind = 'gmail_triage' AND trace_id IS NOT NULL
           ORDER BY duration_ms DESC LIMIT 1)
SELECT name, round(duration_ms) AS ms, operation, model
FROM span WHERE trace_id = (SELECT trace_id FROM t) ORDER BY start_time;
```

Slowest LLM calls this week, with the prompt start:

```sql
SELECT start_time, role, model, round(duration_ms) AS ms, substr(input_messages, 1, 200) AS prompt
FROM v_llm_calls WHERE start_time >= date('now', '-7 days') ORDER BY duration_ms DESC LIMIT 10;
```

Which tools does the chat agent use, and how often do they fail?

```sql
SELECT tool, COUNT(*) AS calls, SUM(status = 'ERROR') AS errors, round(AVG(duration_ms)) AS avg_ms
FROM v_tool_calls GROUP BY tool ORDER BY calls DESC;
```

Everything (spans + logs) for one trace, in order. In sqlite3 set the parameter first:
`.parameter set :trace '<trace_id>'` (or inline the literal):

```sql
SELECT start_time AS ts, 'span' AS kind, name AS what, round(duration_ms) AS ms FROM span WHERE trace_id = :trace
UNION ALL
SELECT ts, 'log', level || ' ' || msg, NULL FROM log_entry WHERE trace_id = :trace
ORDER BY ts;
```

Cache effectiveness per model:

```sql
SELECT model, round(SUM(cache_read_tokens) * 100.0 / NULLIF(SUM(input_tokens), 0), 1) AS cache_hit_pct
FROM v_llm_calls GROUP BY model;
```
