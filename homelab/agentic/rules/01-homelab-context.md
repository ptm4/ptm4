# Homelab context — read nothing else first

Auto-loaded every session: current facts and prohibitions only. History and deeper detail live
in `homelab/agentic/runbooks/` (hosts and SSH: runbook 01). Live per-host state (containers,
ports, mounts, timers) is regenerated nightly on opti into `homelab/agentic/generated/`, which
is **not in git**: the local copy is only as fresh as the last `probe.py --wire claude` (check
each file's `Generated:` line), while the `homelab` MCP's `hl_search_docs` always reads opti's
copy. Prefer either over probing a host. If a fact you need is missing here, add it here.

## Hosts

LAN `192.168.1.0/24`, gateway `.1` = TP-Link Archer router, which is also the **DHCP server**.

| Alias | IP | OS | Role |
|---|---|---|---|
| `tux` / `ptm` | .3 | CachyOS / Windows 11 | **You are here.** One workstation, dual-booted (`hostname` tells you which side). The repo lives on the Windows side. Only service: the read-only **asset server** `:8767` on ptm (`E:\Assets`, answers opti only; `homelab/hosts/ptm/asset-server`), behind Pertal's Asset Library page, which shows "offline" when this PC is off or in Linux. Nothing else depends on it. |
| `opti` | .11 | Debian 12 | **Storage + control plane + app tier.** ZFS pool `red` (single 4 TB WD Red Plus) exported as Samba `\\opti\red` = `/srv/red/fs`; share config is `/etc/homelab/samba-red.conf` (source: `homelab/hosts/opti/samba/samba-red.conf`), NOT OMV's smb.conf. OMV is UI/monitoring only. **`red` has no second copy** (the attic cold copy was retired). Agent dispatcher `:9099`, **homelab-db `:9100`** (index + MCP), x86 CI runner, xrdp `:3389`. App tier in `/srv/docker/compose`: dashboard **`webapp.lan:8443`** (v3.Fable), **Pertal** (v4) side by side at `webapp.lan:8444`, Vaultwarden `bitwarden.rpi.lan:443`, notes `:3002`, Dozzle `:9999`, the `discord-*` bots, hltv-api. 31 GB RAM. |
| `rpi` | .10 | Ubuntu 24.04 (RPi 4) | **DNS only — a network appliance.** Pi-hole is the LAN's only DNS (no DHCP); Dozzle agent `:7007`; ARM64 CI runner. **2 containers, and it stays that way**: runbook 10 has the four-part test before adding anything. Boots from a USB SSD. |
| `noblenumbat` | .6 | Ubuntu 24.04 | **Media.** Jellyfin `:8096`, Kavita `:5000`, *arr stack, qBittorrent/SABnzbd/Prowlarr behind Gluetun VPN, Portainer `:9000`. **Uptime Kuma `:3001`** and **ntfy `:2586`** (phone push) live here so they watch opti from outside. YAMS compose at `/opt/yams/`. |
| `android` | .54 | Termux | Galaxy S10. llama.cpp `:8080` (local LLM). **Intermittent, often offline.** |

Canonical dashboard name is **`webapp.lan`**. `webapp.rpi.lan` still resolves as an alias but
is misleading; don't use it in new work. Bare `webapp` does not resolve.

**Single points of failure:** rpi is the only DNS server; opti carries storage, control plane
and the app tier, so an opti outage costs the dashboard, the vault and the bots at once while
the LAN keeps resolving names. That split is deliberate, so rebooting opti is routine.

**opti's boot disk** (ST500DM002, 40k hours; currently `sdb`, but device letters on opti are
NOT stable) holds only the OS. App data (`/srv/docker` = `red/docker-apps`) and homelab.db live
on the pool, so its death costs a reinstall, not data. **Peter has accepted this risk**
(acknowledged in Pertal 2026-09-27): don't raise the reallocated count or the sda one in
reports, reminders or audits. Mention the boot disk only if pending/uncorrectable go non-zero,
reallocated jumps by 20+ at once, or SMART overall-health fails. Trend and thresholds: runbook 10,
"Watching opti's boot disk".

## SSH

For shell access to `opti`, `rpi`, `noblenumbat` or `android`, use the **`homelab-ssh`** skill
(this is the only rule saying so). Use the alias, `ssh opti '<cmd>'`, with no `-i`/`-p`:
`~/.ssh/config` on both boots carries user, port and key. To check an alias, run
`ssh -G <alias> | grep -iE '^(hostname|port|user|identityfile) '`. Never assume one host's key
works on another.

Two key regimes; don't mix them:

1. **Interactive (you, from the workstation).**
   - **tux:** `~/.ssh/homelab` for all four aliases. android is **port 8022, user `u0_a204`**.
     `~/.claude/opti_key` also reaches `ptm@192.168.1.11`.
   - **ptm:** `~/.ssh/optiplex_omv`, `~/.ssh/rpi`, `~/.ssh/noblenumbat`. **No android alias or
     key on this side.**
2. **Collectors/runners (on opti, fanning out):** `~/.ssh/hl_agents`, chosen by `HL_SSH_KEY`
   with targets in `HL_HOSTS`, both in `/etc/hl-agents.env`. The collectors in
   `homelab/tools/collectors/` do their own fan-out via `_hosts.py` with this key; don't
   rewrite them to use the interactive aliases.

Passwordless `sudo` works non-interactively on opti, rpi and noblenumbat. android is unrooted:
privileged commands need adb over localhost.

## Where the repo lives

- **Working copy: `E:\REPO\ptm4` on ptm** (local NTFS). Edit there. From tux the same disk may be
  mounted; check `git status` before assuming it's the same checkout.
- opti's services run from `/srv/red/fs/ptm/repo/ptm4/homelab/`, a `.git`-less snapshot that
  `.github/workflows/opti-deploy.yml` rsyncs on every push. Never edit it; changes go live only
  when Peter pushes.
- `/srv/red/fs/ptm/old repo location/ptm4` on opti is an old checkout with ~98 uncommitted
  files. **Never `rm -rf` or reset it**; Peter reconciles it by hand.
- Every other clone you can reach (tux CIFS mounts, opti's pool) is a deploy or runtime copy
  only, never an edit path. `noblenumbat:~/code/ptm4` no longer exists.

## Never do these

The `PreToolUse` guard (`../harness/README.md`) enforces the ones marked; the rest rely on you.

- **`rm -rf` a ptm4 working copy** *(guard asks)*: run `git status --ignored --porcelain` and
  `git clean -ndx` first and preserve what they list.
- **Hand-edit Samba or OMV config on opti** *(guard denies)*: `/etc/samba/*` is OMV leftovers;
  edit `homelab/hosts/opti/samba/samba-red.conf` and deploy by copy.
- **Edit `discord-*` bot files on opti** *(guard denies)*: manage bots through the webapp; source
  is `homelab/hosts/opti/apps/discord-*/`.
- **Edit `/srv/docker/compose/webapp/` on opti** *(guard denies)*: deploy target, reverted by the
  next `opti-apps-deploy.yml` run. Edit `homelab/hosts/opti/apps/webapp.v3.Fable/` (the app on
  :8443). `webapp.v2.legacy/` and `webapp.v3.Astra/` were removed in Nov 2026 (git tags
  `webapp-v2-legacy-final`, `webapp-v3-astra-final`).
- **`git commit`, `--amend`, `push` or `reset --hard`** *(guard denies)*: Peter commits his own
  work. Make the change and say what needs committing. Sole exception: the `doc-builder` agent's
  `docs: auto-update` commit after one of his commits.
- **Enable DHCP in Pi-hole** *(guard only reminds, does not block)*: the router is the DHCP
  server; two DHCP servers race and present as "all the servers are down".

## Ask the database before you probe

opti's **homelab-db** (`:9100`) indexes every collector report since June 2026, host inventory,
container change history, and full-text over every runbook and rule. This repo gets it as the
`homelab` MCP server (`.mcp.json`):

- `hl_search_docs`: **try first for any "how does X work here" question.**
- `hl_status`: current health. `hl_host <host>`: everything about one box.
- `hl_changes`: what changed and when. `hl_metrics`: long-range trends.
- `hl_query` + `hl_schema`: read-only SQL for anything else.

Tools missing? `HL_DB_TOKEN` isn't set where Claude Code launched (on ptm a Windows *user* env
var, which needs an app restart; on tux, export it in the shell). It shows as 401. SSH is a fine
fallback, but check here first. Details: runbook 09.

## Collectors and alerts

Collectors (homelab-doctor and network-report every 30 min; hardware, software,
journald-hunter, persistence-auditor daily) run on opti as `hl-collector@<name>.service` from
systemd timers, not GitHub Actions. Logs: `journalctl -u 'hl-collector@*'`. Alerts go to ntfy
(topic `homelab`, via `homelab/tools/notify.py`): failed units page via `OnFailure=`, and each
ingest cycle pages new criticals and stale feeds once, plus a "resolved". To alert from new
code, `from notify import notify`; never build a second channel.

## Working conventions

- Read-only investigation (status, logs, `df`, `docker ps`) needs no approval. For a
  state-changing command, say what you're about to do in one line, then do it.
- Dashboard changes go through the `add-to-webapp` skill (board cards: `add-webapp-widget`).
- The webapp frontends are Vite builds shipped by CI on opti; there is no live-on-copy path.
  A change reaches `webapp.lan` only once Peter commits and pushes.

## Pertal Console

The approved Console adds full root Cockpit access without login for opti/rpi/noblenumbat,
through private SSH-to-bridge gateways on opti. Its operations bypass Pertal jobs/audit,
holds and the removed host reboot precheck. Existing authenticated `:9090` endpoints remain.
Setup, patched package requirements, security gates and rollback:
`homelab/hosts/opti/apps/cockpit-gw/README.md`. Deployment follows Peter's push; report host
setup, local checks, deployment, browser verification and acceptance separately.
