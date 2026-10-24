# DECISIONS

Append-only log of decisions with a real trade-off: what was chosen, what was
rejected, and why. Newest at the bottom.

## 2026-10-10 — Test dates must not expire

**Chose:** far-future fixed dates (2099, which shares 2026's calendar) for tests
that book through the reservation service.

**Rejected:**
- Freezing the clock with `time-machine` — a new dev dependency that patches
  the clock globally.
- Dates relative to `date.today()` — would mean rewriting the weekday-dependent
  recurring-booking tests.

**Why:** the reservation tests hardcoded 2026-10 dates; once 2026-10-01 passed,
the past-date guard (C1) rejected them and CI went red on every branch (#4).
Fixed 2099 dates keep the tests readable and deterministic with the smallest
diff.

**Trade-off:** any new test that reserves through the service, or a lookup that
may gain a past-date guard, must also use a future date.

## 2026-10-24 — Sign-in fails closed without `PLUME_SECRET_KEY` (PLAT-SEC-01)

**Approved by Evan 2026-10-24**, matching homestar's PLAT-SEC-01 gate.

**Chose:** no default signing secret. When `PLUME_SECRET_KEY` is unset or empty
the app keeps serving `/health` and public pages, but refuses every sign-in
(`POST /auth/login` and `POST /login` return 503 "Login not configured"; the
`/login` page shows the notice instead of the form), never signs a token, and
refuses every presented bearer token (503) or session cookie (redirect to
`/login`). Seed-on-start takes the demo operator's password from
`PLUME_SEED_OPERATOR_PASSWORD` and skips seeding when it is unset or empty.

**Rejected:**
- Refusing to start without the key. Closer to a crash than to homestar's
  behaviour, which keeps serving and says what is wrong; a crash-looping service
  also hides `/health` and the public booking page.
- A dev-only opt-in such as `PLUME_ENV=dev` that re-enables a default. It is one
  more variable that could be left on in production, and a local key is one
  `export` away (README). Tests set a key in an autouse fixture.
- Keeping `plume-dev` for seed-on-start. It is printed in the public README, so
  any seeded deploy had a known operator login.

**Why:** the old `dev-secret-change-me` fallback is in a public repo. A deploy
missing the variable signed sessions with it, so anyone could forge an operator
token. Failing closed makes the misconfiguration visible instead of exploitable.

**Trade-off:** local runs need `PLUME_SECRET_KEY` exported; a deploy with
`PLUME_SEED_ON_START=1` but no `PLUME_SEED_OPERATOR_PASSWORD` boots with no
demo data. Key length (≥32 bytes) is still advice, not enforced.
