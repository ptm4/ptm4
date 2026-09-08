# Rolling back the Homarr redesign (webapp v2 → v1)

The v2 overhaul (Fastify backend + React/Vite frontend, 2026-08-10/11) shipped with
three independent escape hatches. Use the cheapest one that fits the situation.

**Status: v2 is live on rpi** — deployed by direct rsync (the fast-iteration path), not
by CI. The repo carries the same code; a `git push` re-deploys it identically through
`rpi-deploy.yml`. Until that push lands, the Pi is ahead of `main`.

## Safety net inventory

| Artifact | Where | What it holds |
|---|---|---|
| Git tag `webapp-v1` | repo (local until pushed: `git push origin webapp-v1`) | Source tree at `976d77d`, the last pure-v1 commit |
| `/srv/docker/compose/webapp-v1-snapshot-2026-08-10` | rpi | Byte-for-byte copy of the deployed v1 app incl. warm `node_modules` |
| `/srv/docker/compose/arch_data-v1-snapshot-2026-08-10.tgz` | rpi | The `compose_arch_data` volume (fragments + vitals) before v2 ever wrote `/arch-data/ui/` |

## Option 0 — you just don't like the new look (no rollback needed)

The entire v1 frontend stays live at **`https://webapp.rpi.lan:8443/legacy/`** during the
transition. Bookmark it; nothing else required.

## Option 1 — revert via git (normal path, ~2 min via CI)

```bash
git checkout webapp-v1 -- homelab/hosts/rpi/webapp .github/workflows/rpi-deploy.yml .github/workflows/checks.yml homelab/hosts/rpi/docker-compose.yml
git commit -m "revert webapp to v1"
git push
```

The push triggers `rpi-deploy.yml`, which redeploys v1 and restarts the containers.
(If v2 renamed `frontend/` → `frontend-legacy/`, the checkout above restores the v1 layout;
the deploy rsync `--delete` clears v2 leftovers on the Pi.)

## Option 2 — CI is broken, restore on the Pi directly

```bash
ssh rpi
cd /srv/docker/compose
mv webapp webapp-v2-broken-$(date +%F)     # keep the evidence, never rm -rf
cp -a webapp-v1-snapshot-2026-08-10 webapp
# v1 compose command was: npm install ... && node index.js (working_dir /app/backend)
# if compose was already changed for v2, restore docker-compose.yml from the tag first
docker compose up -d webapp && docker compose restart webapp nginx-webapp
```

## Option 3 — /arch-data was damaged

```bash
ssh rpi
docker compose stop webapp
docker run --rm -v compose_arch_data:/arch-data -v /srv/docker/compose:/backup alpine \
  sh -c 'cd /arch-data && tar xzf /backup/arch_data-v1-snapshot-2026-08-10.tgz'
docker compose start webapp
```

Note: restoring this tarball discards vitals samples and agent fragments collected after
2026-08-10 (agents re-push fragments within a sync cycle) plus any v2 board layouts under
`/arch-data/ui/`.

## What never needs reverting

- **nginx-wg.conf** — v2 made zero changes to it.
- **Certificates, Pi-hole, bots, notes-app, dozzle** — untouched by the redesign.

## Retirement (when v2 is trusted)

Delete the two snapshot artifacts on rpi and the `/legacy/` static mounts + `frontend-legacy/`
SPA files (keep `tokens.css` and any still-standalone subdirs). Peter's call, weeks later.
