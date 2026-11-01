# BLOCKED — what I need from Evan

> **Fleet repo (_system D-036, D-051, D-052):** plume's blockers live in Jira as *Needs Evan*
> tickets (component `plume`; file with `uv run --project ~/Documents/_system sys file-blocker`);
> `sys blockers` mirrors them into the todo dashboard. Two kinds stay here: `[sec]` blockers (the
> security dashboard counts them only here) and anything Jira must not hold — rosters, secrets,
> unpublished writing. Moved 2026-10-31: EA-74.



- [ ] 🔴 [sec] **Before merging/deploying the PLAT-SEC-01 PR: confirm `PLUME_SECRET_KEY` (and, if seeding, `PLUME_SEED_OPERATOR_PASSWORD`) on the Railway service.** Sign-in now fails closed: with `PLUME_SECRET_KEY` unset or empty, `/login` shows "Login not configured" and nobody can sign in. To unblock: Railway dashboard → the plume project → service → Variables. (1) Check `PLUME_SECRET_KEY` is listed by name with a non-empty value of ≥32 characters; if missing, add one from `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. (2) If `PLUME_SEED_ON_START=1` is set, add `PLUME_SEED_OPERATOR_PASSWORD` with a private password (keep it in 1Password); without it the deploy boots with no demo data. (3) If the service keeps `plume.db` on a volume, the already-seeded `rory@plume.test` still has the public README password `plume-dev`; decide whether to wipe that DB so it reseeds with the new password. Then merge the PR.

- [ ] 🔴 [sec] **Before merging/deploying the PLAT-SEC-02 PR (no open operator bootstrap): make sure the Railway deploy seeds its operator.** After this PR, `POST /auth/register` never creates the first operator, and the Railway service has no volume, so each deploy boots with an empty DB and **no way to sign in** unless the seed runs. To unblock: Railway dashboard → plume project → service → Variables: confirm `PLUME_SEED_ON_START=1` and a non-empty `PLUME_SEED_OPERATOR_PASSWORD` (private, keep it in 1Password), alongside `PLUME_SECRET_KEY`. Then merge. Alternative for a one-off operator: `railway ssh` into the service and run `uv run python -m plume.auth.cli create-operator --email <you>` (lost on the next deploy without a volume). Until this PR deploys, the live site still lets whoever registers first on an empty DB become operator, so merge soon.

<!--
Add a line the moment something else needs Evan, in this shape (drop the leading `>`):
> - [ ] 🔴 <blocking item> — how to unblock: <action, where, URL/path/env-var>
> - [ ] 🟡 <nice-to-have item> — how to unblock: <...>
The blocked-router scans raw lines and does not skip HTML comments, so the examples are
`>`-prefixed to keep them from being mirrored as real blockers.
Only open checkbox lines are mirrored into Evan's todo dashboard.
Open questions that are Rory's to answer live in PRD.md §16 ("Decisions & Open Questions for Rory"), not here.
-->
