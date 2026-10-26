# Installation — AI Sales System Pilot

## Requirements
- Python 3.11+ (Docker image uses Python 3.12), or Docker Engine + Docker Compose v2.
- Do not use production customer data with this release: the dashboard and metrics store is in-memory demo data.

## Local Python run

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements-dashboard.txt
export DASHBOARD_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python scripts/preflight.py
uvicorn app.dashboard.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. Enter the exact token configured in `DASHBOARD_API_TOKEN` and organization `org_demo`. `/health` is public; protected API routes require a bearer token.

## Docker Compose

```bash
cp .env.example .env
# Edit .env and replace DASHBOARD_API_TOKEN with a unique random value.
set -a; . ./.env; set +a
python scripts/preflight.py
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

The compose port binds to `127.0.0.1` only. Put a TLS reverse proxy and identity-aware access layer in front of it if remote access is required. Never expose the demo API directly to the public internet.

## Test

```bash
python -m pip install -r requirements-dashboard.txt
python -m pytest -q
```

The tests validate deterministic code paths. They do not validate provider accounts, Supabase configuration, DNS, TLS, backup restoration or production infrastructure.
