.PHONY: help dev api web obs-sql obs-ui

OBS_DB ?= api/data/observability.db

help:
	@echo "make dev   start API + Inngest + dashboard (Ctrl-C stops all)"
	@echo "make api   start API only"
	@echo "make web   start dashboard only"
	@echo "make obs-sql  query observability.db with sqlite3"
	@echo "make obs-ui   browse observability.db in Datasette"

# Start everything (Ctrl-C stops all)
dev:
	@trap 'kill 0' INT; \
	(cd api && uv run python -m app.main) & \
	npx --yes inngest-cli@latest dev -u http://localhost:8000/api/inngest & \
	(cd web && npm run dev) & \
	wait

api:
	cd api && uv run python -m app.main

web:
	cd web && npm run dev

obs-sql:   ## open the observability DB read-only in sqlite3 (try: SELECT * FROM v_runs ORDER BY run_id DESC LIMIT 10;)
	sqlite3 -readonly -box -header $(OBS_DB)

obs-ui:    ## browse/query the observability DB in Datasette (read-only) at http://127.0.0.1:8001
	uvx datasette $(OBS_DB) --port 8001 --setting sql_time_limit_ms 5000
