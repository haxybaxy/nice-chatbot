# Root recipes: run the whole stack. Each subproject keeps its own tooling and justfile — `cd`
# there for everything else (checks, tests, migrations, infra). First-time setup is per
# subproject: backend/README.md and frontend/README.md (their `.env`, `uv sync`, `npm ci`).

# List all recipes
default:
    @just --list

# Start Postgres (backend/docker-compose.yml) and wait until it is healthy
db-up:
    cd backend && just db-up

# Stop Postgres (data volume is kept)
db-down:
    cd backend && just db-down

# Apply pending backend migrations
migrate:
    cd backend && just migrate

# Serve everything in one terminal: Postgres, then the API on :8000 and the SPA on :3000 (Ctrl-C stops both)
dev: db-up migrate
    #!/usr/bin/env bash
    set -euo pipefail
    # The servers and their reloaders share this shell's process group. Ctrl-C already reaches
    # every one of them; stop_group covers the other ways out (a server exits, `just` is killed
    # by a supervisor) by signalling the rest of the group once — never this shell or its parent
    # `just`, so the trap cannot re-fire on its own signal — and reports a clean exit.
    stop_group() {
        trap - INT TERM EXIT
        pgrep -g 0 | grep -vx -e $$ -e $PPID | xargs kill -TERM 2>/dev/null || true
        wait
        exit 0
    }
    trap stop_group INT TERM EXIT
    (cd backend && just dev) &
    (cd frontend && just dev) &
    wait

# Serve everything with mprocs — one pane per process (api, web, db logs), see mprocs.yaml
mprocs: db-up migrate
    mprocs
