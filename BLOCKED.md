# BLOCKED — what I need from Evan

- [ ] 🔴 **Validate SBA loan eligibility / financing structure before we finalize the financial model.** SBA rules (SOP 50 10 8) generally treat a pure space-*rental* salon-suite business as an ineligible "passive business" — see PRD.md §3. How to unblock: book a free session with the **Nevada SBDC (UNLV)** — unlv.edu/sbdc or 702-895-5019 — or call an SBA-preferred lender, and confirm whether the membership/services structure in §7 qualifies (or whether we go conventional-loan instead). It's free and non-committal. Until this is settled, the loan-path numbers in §12 are provisional.

- [ ] 🔴 **Before merging/deploying the PLAT-SEC-01 PR: confirm `PLUME_SECRET_KEY` (and, if seeding, `PLUME_SEED_OPERATOR_PASSWORD`) on the Railway service.** Sign-in now fails closed: with `PLUME_SECRET_KEY` unset or empty, `/login` shows "Login not configured" and nobody can sign in. To unblock: Railway dashboard → the plume project → service → Variables. (1) Check `PLUME_SECRET_KEY` is listed by name with a non-empty value of ≥32 characters; if missing, add one from `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. (2) If `PLUME_SEED_ON_START=1` is set, add `PLUME_SEED_OPERATOR_PASSWORD` with a private password (keep it in 1Password); without it the deploy boots with no demo data. (3) If the service keeps `plume.db` on a volume, the already-seeded `rory@plume.test` still has the public README password `plume-dev`; decide whether to wipe that DB so it reseeds with the new password. Then merge the PR.

<!--
Add a line the moment something else needs Evan, in this shape (drop the leading `>`):
> - [ ] 🔴 <blocking item> — how to unblock: <action, where, URL/path/env-var>
> - [ ] 🟡 <nice-to-have item> — how to unblock: <...>
The blocked-router scans raw lines and does not skip HTML comments, so the examples are
`>`-prefixed to keep them from being mirrored as real blockers.
Only open checkbox lines are mirrored into Evan's todo dashboard.
Open questions that are Rory's to answer live in PRD.md §16 ("Decisions & Open Questions for Rory"), not here.
-->
