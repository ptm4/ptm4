# Homelab Drift

> ⚙️ **AUTO-GENERATED — do not hand-edit.** Rewritten each run by `homelab/Tools/architecture/gen-agentic-docs.py` from `GET /api/architecture/data`. Any manual change here is overwritten on the next run.
> Generated: `2026-07-26T22:16:24+00:00`


Where the architecture map and reality disagree, as of the last agent sync. This is a TODO list, not a health report: an empty section means nothing to do, not that everything is fine — cross-check `90-homelab-inventory.md`'s sync ages.


## Running, not described on the map · 0

A container an agent found that has no matching node in the architecture data. Either add it to `homelab/Tools/architecture/build-arch-data.py`'s NODES, or if it's expected to be transient/unmanaged, leave it — this list is informational, nothing acts on it automatically.

_none_


## Described, not detected · 0

A node on the map with a `container` field that the matching host's agent did NOT find — likely renamed, removed, or recreated under a different container name. A compose recreate can also leave the old container behind under a `-old-<id>` suffix; that shows up as a *separate* entry in the section above, since it's a different container name.

_none_
