# plume

`plume` is the custom **salon-suite booking & management** app — the "build-your-own"
option evaluated against Vagaro/GlossGenius in [PRD.md §9.2](./PRD.md) and implemented
task-by-task (test-first) in [TASKS.md](./TASKS.md). It handles the operator's core
workflow: onboarding stylists (members), managing front-of-house day-rental stations and
back-of-house monthly suites, booking/cancelling reservations with double-booking
protection, and running monthly billing (suite rent + day-rate rollups) — all behind a
role-gated API (operator vs. member).

## Stack

- **Python 3.12+**
- **FastAPI** (HTTP API) + **Uvicorn** (ASGI server)
- **SQLModel** (SQLAlchemy + Pydantic) over **SQLite**
- **pytest** + **httpx** (tests), **ruff** (lint), **ty** (typecheck), **prek** (pre-commit)
- **uv** for dependency management and running everything

## Setup

```bash
uv sync            # create the venv and install all deps (incl. dev group)
```

## Run the dev server

```bash
export PLUME_SECRET_KEY="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run uvicorn plume.main:app --reload
```

Sign-in **fails closed**: without `PLUME_SECRET_KEY` the app still serves `/health` and
public pages, but `/login` and `POST /auth/login` answer 503 "Login not configured" and
every bearer token or session cookie is refused. There is no built-in default secret.

- Interactive API docs (Swagger UI): <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health> → `{"status": "ok"}`

## Deploy (Railway)

Railpack detects FastAPI via the repo-root `main.py` (`uvicorn main:app` on `$PORT`).
Set these service variables:

- `PLUME_SECRET_KEY` — **required.** JWT signing secret, ≥32 bytes. Unset or empty, nobody
  can sign in (see above).
- `PLUME_SEED_ON_START=1` — load demo data on boot if missing. The demo operator
  (`rory@plume.test`) gets its password from `PLUME_SEED_OPERATOR_PASSWORD`; if that is
  unset or empty the seed is skipped, so a deploy never carries a published password.
- `PLUME_DATABASE_URL` — optional SQLAlchemy URL; defaults to `sqlite:///plume.db`.

## Tests, lint, typecheck

```bash
uv run pytest                 # run the test suite (fast, no coverage)
uv run ruff check .           # lint
uv run ty check               # typecheck
prek run --all-files          # all pre-commit hooks (ruff + ty)
```

### Coverage (opt-in)

Coverage is **not** wired into the default `pytest` run — it stays fast and quiet.
Run it explicitly when you want it:

```bash
uv run pytest --cov=plume --cov-report=term-missing
```

CI enforces a coverage floor with `--cov-fail-under=88` (measured total ≈ 94% with
branch coverage on). Coverage config lives in the `[tool.coverage.*]` sections of
`pyproject.toml`.

## Seed demo data

Populate a local SQLite DB (`./plume.db`) with a realistic demo dataset — one operator,
stations, suites (a couple assigned), a mix of member statuses, some reservations, and one
monthly billing run:

```bash
uv run python -m plume.seed
```

The seed calls the real service functions (so the data obeys the business rules) and is
**idempotent** — re-running it is a no-op once the demo operator (`rory@plume.test`)
exists. To reseed from scratch, delete `plume.db` first.

The local seed signs the demo operator in as `rory@plume.test` / `plume-dev`. That password
is public, so it is for a local `plume.db` only; deploys seed through
`PLUME_SEED_OPERATOR_PASSWORD` instead (see Deploy).

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: `uv sync` → `ruff check`
→ `ty check` → `pytest` → coverage gate. **CI runs checks only** — it never deploys,
pushes to a branch, or auto-merges.

## Architecture map

```
plume/
  main.py            # FastAPI app factory + router wiring; GET /health
  db.py              # SQLModel engine, init_db(), get_session() dependency (in-memory for tests)
  logging_conf.py    # idempotent stdlib logging setup (level via PLUME_LOG_LEVEL)
  seed.py            # demo-data seed script (python -m plume.seed)
  auth/              # users, password hashing, JWT tokens, operator/member role guards
  members/           # stylists/members: onboarding rules, lifecycle status, CRUD
  spaces/            # inventory: front Stations (day-rental) + back Suites (monthly)
  reservations/      # front day-rental booking, cancellation, availability, recurring holds
  billing/           # invoices + line items: monthly suite rent, day-rate rollups, state transitions

tests/               # mirrors the package layout; shared fixtures/factories in conftest.py
```

Each feature package owns its own `models.py` / `service.py` / `router.py`. Business rules
live in the service layer (errors are **raised**, never swallowed); routers translate those
errors to HTTP status codes at the boundary.
