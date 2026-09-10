# Rolling back v3.Fable

Written at go-live (2026-09-10), before it was needed, because a rollback plan
authored mid-outage is a plan written by the least qualified person you will ever
be. The premise of the whole scheme: **nothing on opti needs to be unpicked by
hand** — the deploy is fully derived from the repo, so the repo is where you roll
back.

## The one-command version

```bash
git revert <the-flip-commit> && git push
```

Where `<the-flip-commit>` is the commit that pointed `.github/workflows/
opti-apps-deploy.yml` (and `checks.yml`) at `webapp.v3.Fable/`. Reverting it points
the pipeline back at `webapp.v2.legacy/` — still in the repo, byte-for-byte the app
that ran for months — and the push redeploys it. The rsync in the workflow runs with
`--delete`, so v3's files are removed from `/srv/docker/compose/webapp/` in the same
pass. Total window is the same 2–3s container restart every deploy has.

## What does NOT roll back with it, and why that is fine

- **The audit trail** (`arch-data/audit/*.jsonl`). v2 never writes there, never reads
  there, and the named volume persists. When v3 returns, its history is intact.
- **UI state under `/api/ui`** (settings, favourites). Shared shapes, frozen since
  v2 — that freeze was maintained all through v3 precisely so this line could be
  this short.
- **nginx-wg.conf's `/api/events` block.** Harmless under v2 — the location proxies
  to a route that answers 404, which nothing in v2 calls. Leave it; it saves a
  config edit in both directions.
- **homelab-db, the collectors, the doctor.** Not part of this app. The 2026-09-10
  fixes to them (service_checks idempotence, host definitions) stand on their own
  merits regardless of which webapp is serving.

## What breaks under v2 if you do roll back

Honesty section — reverting costs these, they are v3-only:

- The Monitor (btop page), the Docs page, `/logs` as a rail page, the couch Home.
- Stepped jobs: v2 actions go back to one-toast feedback. The audit *file* survives
  but nothing writes to it until v3 returns.
- The corrected host roles and blast-radius copy. v2 still believes rpi serves the
  dashboard — its confirmation prompts will be wrong about what a reboot costs.
  Tolerable for the hours a rollback should last; not for weeks.

## If the deploy itself is the thing that is broken

The workflow's smoke gate (77 routes, compared to the committed baseline) runs
inside the deployed container and fails the run before nginx restarts, so a bad
build mostly cannot land. If something slips past it anyway, the fastest exit is
still the revert above — do not hand-edit `/srv/docker/compose/webapp/`; the next
push overwrites it, and now there are two problems.
