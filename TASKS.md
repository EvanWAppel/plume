# TASKS — `plume` booking & management app

Implements the custom salon-suite software from **[PRD.md](./PRD.md) §9.2** (the "build-your-own" option Rory evaluates against Vagaro/GlossGenius). Built **test-first (TDD)**, walking-skeleton-first, and grouped so multiple agents can work in parallel without colliding.

## Stack & conventions
- **Python 3.12+**, **FastAPI**, **SQLModel** (SQLAlchemy + Pydantic), **SQLite**, **Uvicorn**, **httpx** (API tests), **pytest**.
- Tooling: **uv** (deps + runner), **ruff** (lint), **ty** (typecheck), **prek** (pre-commit), stdlib **logging**.
- Rules (from `../CLAUDE.md`): use `uv` for everything (`uv run python`, `uv add`, `uv add --dev`); **never edit `pyproject.toml` deps by hand**; **TDD with pytest**; **fixtures in `conftest.py` to DRY**; **don't hide or wrap errors**; **log for debuggability**; **don't push to main**.

## How to run
```bash
uv run pytest                 # tests (TDD loop)
uv run uvicorn plume.main:app --reload   # dev server
uv run ruff check .           # lint
uv run ty check               # typecheck
prek run --all-files          # pre-commit hooks
```

## Module ownership (so parallel agents don't touch the same files)
```
plume/
  main.py            # app factory + router wiring        (Phase 0, then F)
  db.py              # engine, session, init              (Phase 0)
  logging_conf.py    # logging setup                      (Phase 0 / X)
  members/           # Group A  — stylists/members
  spaces/            # Group B  — stations + suites
  reservations/      # Group C  — front day-rental booking
  billing/           # Group D  — memberships + invoices
  auth/              # Group E  — users, roles, tokens
  web/               # Group F  — minimal UI
  community/         # Group G  — events + gallery (Phase 2)
tests/
  conftest.py        # shared fixtures (DB, client, factories)  (Phase 0)
  <mirrors package layout>
```
**Each package owns its own models/service/router/tests** → an agent can own a whole group with minimal merge conflicts. Shared files (`main.py`, `db.py`, `conftest.py`) are established in Phase 0; later groups *append* (add a router include, add a fixture) rather than rewrite.

## Legend
`[ ]` todo · `[x]` done · **Dep:** prerequisite task IDs · _TDD:_ the test to write first.

---

## Phase 0 — Walking Skeleton  ⚡ DO FIRST (sequential, one agent)
Goal: the thinnest end-to-end slice proving the whole pipeline runs — *a stylist reserves an available front station for a date, and a double-booking is rejected.* No auth, no UI, minimal models.

- [x] **S1** — Init uv project + package layout (`plume/`, `tests/`), Python 3.12 pin. `uv add fastapi "uvicorn[standard]" sqlmodel`; `uv add --dev pytest httpx ruff ty prek`.
- [x] **S2** — `plume/logging_conf.py`: configure stdlib logging (level via env, structured-ish format). _TDD: test that `configure_logging()` is idempotent and sets the root level._
- [x] **S3** — `plume/db.py`: SQLModel engine + `get_session()` dependency + `init_db()`. Support an **in-memory SQLite** for tests. _TDD: `init_db()` creates tables; a session round-trips a trivial row._
- [x] **S4** — `tests/conftest.py`: fixtures for a fresh in-memory DB, a `TestClient`, and simple factories (`make_member`, `make_station`). _(DRY foundation for every other group.)_
- [x] **S5** — Minimal models (in their packages): `members/models.py::Member` (id, name, email), `spaces/models.py::Station` (id, name, active), `reservations/models.py::Reservation` (id, member_id, station_id, date). _TDD: each model persists and reloads._
- [x] **S6** — `reservations/service.py::reserve_station(session, member_id, station_id, date)`: creates a reservation; **raises `StationUnavailableError`** if that station is already reserved for that date. _TDD (write first): reserve succeeds; second reserve of same station+date raises; different date/station succeeds._
- [x] **S7** — API: `reservations/router.py` `POST /reservations` (201 → reservation; 409 on conflict) and `spaces/router.py` `GET /stations/available?date=` (list free stations). `GET /health` in `main.py`. Wire routers in `plume/main.py::create_app()`. _TDD (write first): httpx end-to-end — seed member+station, POST reserve → 201; POST duplicate → 409; available list excludes the reserved station._
- [x] **S8** — Green gate: `uv run pytest` all pass, `uv run ruff check .` clean, `uv run ty check` clean. Server boots (`GET /health` → 200). **This is the "it works" milestone.**

---

## Cross-cutting / infra — Group X (any agent, mostly parallel)
- [x] **X1** — `prek` config (`.pre-commit-config.yaml`) running ruff + ty; `prek install`. **Dep:** S1.
- [x] **X2** — `ruff` + `ty` config in `pyproject.toml` tool sections (line length, target-version, rule selection). **Dep:** S1.
- [x] **X3** — GitHub Actions CI: `uv sync`, `pytest`, `ruff`, `ty` on PR. **Dep:** S8. _Note: CI only; do not auto-push to main._
- [x] **X4** — pytest coverage config + `--cov` gate (e.g., fail under 80%). **Dep:** S8.
- [x] **X5** — `README.md` (run/dev/test instructions) + seed script `plume/seed.py` for demo data. **Dep:** S8.

---

## Group A — Members / stylists  (owns `plume/members/`)
**Dep:** S5. Parallel with B, E.
- [x] **A1** — Expand `Member`: phone, cosmetology license #, license-expiry, insurance-on-file (bool), tier (`OPEN_STUDIO`/`PRIVATE_STUDIO`), status (`PROSPECT`/`ACTIVE`/`INACTIVE`), created-at. _TDD: defaults + enum validation._
- [x] **A2** — `members/service.py`: `onboard_member`, `update_member`, `deactivate_member`, `list_members(status=…)`. _TDD (first): onboarding requires license #; deactivate flips status; list filters._
- [x] **A3** — Onboarding rule: a member cannot be set `ACTIVE` without license # **and** insurance-on-file. _TDD (first): activating without insurance raises `OnboardingIncompleteError`._
- [x] **A4** — `members/router.py`: `POST /members`, `GET /members`, `GET /members/{id}`, `PATCH /members/{id}`. _TDD (first): CRUD happy paths + 404 + validation 422._
- [x] **A5** — Wire router in `create_app()`; add `make_member` factory options to conftest. **Dep:** A4.

## Group B — Spaces / inventory  (owns `plume/spaces/`)
**Dep:** S5. Parallel with A, E.
- [x] **B1** — Split space types: `Station` (front, day-rentable) and `Suite` (back, monthly). Shared fields (number/name, active, notes); `Suite` adds `monthly_rate`, `occupant_member_id` (nullable). _TDD: both persist; suite occupancy nullable._
- [x] **B2** — `spaces/service.py`: `add_station`, `add_suite`, `deactivate_space`, `list_stations(active=…)`, `list_suites(vacant=…)`. _TDD (first): listing filters by active/vacancy._
- [x] **B3** — `assign_suite(session, suite_id, member_id)` / `vacate_suite`: a suite holds ≤1 occupant; assigning an occupied suite raises `SuiteOccupiedError`. _TDD (first): assign, double-assign raises, vacate frees it._
- [x] **B4** — `spaces/router.py`: `POST /stations`, `POST /suites`, `GET /stations`, `GET /suites`, suite assign/vacate endpoints. _TDD (first): endpoints + conflict 409._
- [x] **B5** — Wire router; add `make_suite` factory to conftest. **Dep:** B4.

## Group C — Reservations (front day-rental)  (owns `plume/reservations/`)
**Dep:** S6, S7, A1, B1. Parallel with D.
- [x] **C1** — Harden `reserve_station`: reject reservations for inactive stations and inactive members; reject past dates. _TDD (first): each rejection raises a specific error._
- [x] **C2** — `cancel_reservation` + `list_reservations(date=…, member_id=…, station_id=…)`. _TDD (first): cancel frees the slot; filters work._
- [x] **C3** — Availability query `available_stations(session, date)` excludes reserved + inactive. _TDD (first): mixed active/reserved set returns the right free list._
- [x] **C4** — Optional part-time recurring hold (e.g., "every Tuesday for a month") → expands to individual reservations, conflict-checked. _TDD (first): expansion + partial-conflict handling._
- [x] **C5** — Reservation endpoints: `DELETE /reservations/{id}`, `GET /reservations?date=`. _TDD (first): list + cancel over HTTP._

## Group D — Memberships & billing  (owns `plume/billing/`)
**Dep:** A1, B1 (suites). Parallel with C.
- [x] **D1** — `Invoice` + `LineItem` models (member_id, period, amount, status `DRAFT/SENT/PAID/VOID`, kind `SUITE_RENT/DAY_RATE/RETAIL/OTHER`). _TDD: persist + status transitions._
- [x] **D2** — `billing/service.py::generate_monthly_invoices(session, period)`: one suite-rent invoice per occupied suite at its `monthly_rate`. _TDD (first): N occupied suites → N invoices; vacant suites skipped; idempotent per period._
- [x] **D3** — Day-rate charges: rolling up a member's reservations for a period into `DAY_RATE` line items at a configurable rate. **Dep:** C2. _TDD (first): 3 reservations × rate = correct total._
- [x] **D4** — `mark_paid` / `void_invoice` with legal state transitions (can't pay a void invoice). _TDD (first): invalid transition raises._
- [x] **D5** — `billing/router.py`: `POST /billing/run?period=`, `GET /invoices?member_id=&status=`, `POST /invoices/{id}/pay`. _TDD (first): run generates, list filters, pay transitions._

## Group E — Auth & roles  (owns `plume/auth/`)
**Dep:** S4. Mostly parallel (touches `main.py` deps late).
- [x] **E1** — `User` model (email, hashed password, role `OPERATOR`/`MEMBER`, optional link to `Member`). _TDD: password is hashed, never stored plaintext._
- [x] **E2** — Password hashing + `authenticate(email, password)`. _TDD (first): correct pw authenticates, wrong pw fails._
- [x] **E3** — Token issuance (JWT or itsdangerous) + `get_current_user` dependency. _TDD (first): valid token resolves user; bad/expired token → 401._
- [x] **E4** — Role guard dependency `require_operator`; protect write endpoints (members/spaces/billing). **Dep:** A4, B4, D5. _TDD (first): member token → 403 on operator route; operator token → 200._
- [x] **E5** — `POST /auth/login`, `POST /auth/register` (operator-gated). _TDD (first): login returns token; register requires operator._

## Group F — Minimal Web UI  (owns `plume/web/`)
**Dep:** S8, and the API groups it surfaces (A4/B4/C5/D5). Do after core API is green.
- [x] **F1** — Choose UI approach (HTMX + Jinja templates recommended for a self-service, low-JS app). Serve from FastAPI. _TDD: index route renders 200._
- [x] **F2** — Operator dashboard: members list, spaces/occupancy, run billing. _TDD: renders seeded data._
- [x] **F3** — Stylist view: available stations for a date + book/cancel. _TDD: booking via UI hits the API and reflects state._
- [x] **F4** — Auth screens (login) + session handling. **Dep:** E5.

## Group G — Community / cultural hub tooling  (owns `plume/community/`)  — Phase 2
**Dep:** S8. Lowest priority (PRD frames the hub as a light marketing engine, not core software).
- [x] **G1** — `Event` model + CRUD (title, datetime, capacity, RSVP list). _TDD (first): capacity cap enforced on RSVP._
- [x] **G2** — `ArtPiece` model for the consignment gallery (artist, title, price, commission %, status `ON_DISPLAY/SOLD`). _TDD (first): selling computes salon commission + artist payout._
- [x] **G3** — Public endpoints: upcoming events + current gallery. _TDD: list endpoints._

---

## Dependency graph (for scheduling agents)
```
S1→S2→S3→S4→S5→S6→S7→S8   (Phase 0, sequential, one agent)
                         ├─ A (members)   ─┐
                         ├─ B (spaces)    ─┤→ C (reservations) ─┐
                         ├─ E (auth)       │→ D (billing)       ─┤
                         └─ X (infra)      │                    ├→ F (web)
                                           └────────────────────┘
                                                          G (community, Phase 2)
```
**Suggested parallel assignment after S8:** Agent-1 = A, Agent-2 = B, Agent-3 = E, Agent-4 = X. Then Agent-1 = C, Agent-2 = D (both depend on A+B). F and G last.

## Definition of done (every task)
1. Failing test written first (`uv run pytest` red). 2. Minimal code to green. 3. `ruff` + `ty` clean. 4. Errors are raised, not swallowed. 5. Logging added at decision points. 6. Checkbox flipped to `[x]` with the commit.

## Progress
- Phase 0: 8/8 ✅ · X: 5/5 ✅ · A: 5/5 ✅ · B: 5/5 ✅ · C: 5/5 ✅ · D: 5/5 ✅ · E: 5/5 ✅ · F: 4/4 ✅ · G: 3/3 ✅
