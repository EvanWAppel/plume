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
