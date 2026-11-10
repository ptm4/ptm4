# Pertal takes over :8443 (audit idea B-2) — cutover and v3 retirement

Approved by Peter 2026-11-10 ("do A to E"). Steps A to C are in the working tree / pushed
separately; this file is the checklist for **D (cutover, Sat 2026-11-21)** and **E (retire
v3.Fable, about Sat 2026-12-05, after two quiet weeks)**. Delete this file once E is done.

Background: `homelab/hosts/opti/apps/WEBAPP-V4-PLAN.md` step 7.

## Before D: preconditions (all must be true)

- [ ] The C changes are pushed and the deploy is green: Pertal on :8444 answers
      `/api/weather/status` (and the other 4 bots), `/api/architecture/data`, `/api/uptime`,
      `/api/pihole/summary`, `/notes/`, `/dozzle/`, and the Bots page saves a setting.
- [ ] `PIHOLE_WEB_PASSWORD` and `KUMA_API_KEY` are in `/srv/docker/compose/.env` (v3 already
      reads them from there, so they should be; check with `grep -c` only, never print them).
- [ ] Peter has used the Bots page on :8444 at least once for a real change.

## D. Cutover (one commit, nothing else in it)

Edits:

1. `homelab/hosts/opti/apps/nginx-wg.conf` — swap the two server blocks' ports:
   - Pertal block: `listen 8444 ssl;` → `listen 443 ssl;` (the container's 443 is published as
     host :8443), and `error_page 497 =301 https://$host:8444$request_uri;` → `:8443`.
   - v3 block: `listen 443 ssl;` → `listen 8444 ssl;`, its `error_page 497` → `:8444`, and add
     `webapp.lan` to its `server_name`. Update both blocks' header comments.
2. `homelab/hosts/opti/docker-compose.apps.yml` — comments only (`pertal` "served at :8443",
   nginx-webapp's `8444` line "v3.Fable fallback until retired"). Ports stay as they are.
3. `homelab/hosts/opti/apps/webapp.v4.Pertal/backend/lib/topology.js` — the `webapp` service:
   label `Dashboard v3 (fallback)`, sub `webapp.lan:8444`.
4. Docs: `homelab/agentic/skills/add-to-webapp/SKILL.md` (`:8444` → `:8443`, drop "becomes
   :8443 at cutover"), `homelab/agentic/skills/add-webapp-widget/SKILL.md` (v3 is now :8444,
   fallback only), `homelab/agentic/rules/01-homelab-context.md` (the opti row and the "Never
   edit /srv/docker/compose/webapp/" bullet: the live app is Pertal), `WEBAPP-V4-PLAN.md`
   step 7. Then `python3 homelab/agentic/probe.py --wire claude`.

Nothing else moves: the arch agents, homelab-db ingest, homelab-doctor, gen-agentic-docs and
Uptime Kuma all keep calling :8443 and Pertal now answers the same routes.

Verify (after Peter pushes and the deploy is green):

- `curl -sk https://webapp.lan:8443/api/health` reports `"app":"pertal"`; `:8444` reports v3.
- Kuma: the `/`, `/notes/`, `/dozzle/` monitors stay green (if the `/` monitor checks for a
  keyword from v3's page, change the keyword in Kuma).
- homelab-db: `hl_status` shows no stale `uptime-kuma`, `pihole-stats`, bot or
  `architecture` datasets after the next :12 ingest.
- Each arch agent's next push lands (Pertal Activity shows "reported its inventory").
- Peter's phone: open https://webapp.lan:8443 once. If it shows v3, the old service worker is
  cached; a hard reload (or clearing site data for that origin) fixes it.

Rollback: `git revert` the D commit and push. v3 is still deployed on :8444 the whole time.

## E. Retire v3.Fable (about 2026-12-05, needs its own yes)

Only after two weeks with nothing needing the :8444 fallback.

1. Move the architecture map's `data.json` out of v3's tree **first** — the architecture map
   work owns `homelab/tools/architecture/build-arch-data.py` (its `DEFAULT_OUT`) and the file.
   Then point `PERTAL_ARCH_DATA` (compose + `backend/dev.env`) at the new path.
2. `docker-compose.apps.yml`: remove the `webapp` service, drop `depends_on: webapp` from
   nginx-webapp, remove the `8444` port line; `nginx-wg.conf`: remove the v3 server block
   (its v3-only `/api/llama`, `/api/agents` and `/hls` locations go with it — Pertal has its
   own `/hls`).
3. `.github/workflows/opti-apps-deploy.yml`: remove the v3 build job, the v3 rsync, the
   `restart webapp` step and the v3 smoke step; drop `webapp.v3.Fable/**` from the path
   filter. `checks.yml`: remove the three v3 steps.
4. `homelab/tools/homelab-db/ingest.py`: the deploy-drift dataset hashes
   `/srv/docker/compose/webapp/backend` against `webapp.v3.Fable` — repoint it at Pertal or
   drop it.
5. `homelab/agentic/harness/hooks/homelab-guard.py` (`webapp-deploy-dir` rule) and the rules
   file: the deploy dir becomes `/srv/docker/compose/pertal`.
6. Pertal `user: "0:0"`: chown the `arch_data` volume to 1000:1000 once on opti (Peter's yes),
   then delete that compose line.
7. Peter runs: `git tag -a webapp-v3-fable-final -m "v3.Fable before removal"`, then
   `git rm -r homelab/hosts/opti/apps/webapp.v3.Fable`, commit, and push the tag.

Rollback: restore the folder from the tag and revert the E commit.
