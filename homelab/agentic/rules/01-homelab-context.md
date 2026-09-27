# Homelab context — read nothing else first

This file is auto-loaded every session. It exists so you never have to grep for hosts, keys,
or "where does the repo live". If a fact you need is missing here, add it here.

Deeper detail lives in `homelab/agentic/runbooks/`. Live per-host facts (containers, ports,
mounts, timers) are regenerated nightly into `homelab/agentic/generated/` — prefer those over
probing a host yourself.

## Hosts

LAN is `192.168.1.0/24`, gateway `.1` (a **TP-Link Archer** — earlier docs said "Verizon
router"; that hardware doesn't exist, confirmed 2026-07-31). The servers are SSH-able by alias
from either side of the workstation.

| Alias | IP | OS | Role — what it contains |
|---|---|---|---|
| `tux` / `ptm` | .3 | CachyOS / Windows 11 | **You are here.** One workstation, dual-booted: `tux` is the Linux side, `ptm` the Windows side (where the repo lives). Check which with `hostname`. One service, Windows side only: the read-only **asset server** `:8767` (`E:\Assets`, answers opti only; `homelab/hosts/ptm/asset-server`) behind Pertal's Asset Library page, which says "offline" when this PC is off or in Linux. Nothing else depends on it. |
| `opti` | .11 | Debian 12 | **Storage + control plane + app tier.** ZFS pool `red` (4 TB WD Red Plus) exported as Samba `\\opti\red` = `/srv/red/fs` (share config: `/etc/homelab/samba-red.conf`, NOT OMV's smb.conf); old mergerfs pair = weekly cold copy at `/srv/attic`; OMV for UI/monitoring only; agent dispatcher `:9099`; **homelab-db `:9100`** (queryable index + MCP); x86 CI runner; xrdp `:3389`. **Since 2026-09-10 also the whole app tier** (13 containers in `/srv/docker/compose`): dashboard **`webapp.lan:8443`**, Vaultwarden `bitwarden.rpi.lan:443`, notes `:3002`, Dozzle `:9999`, 5 `discord-*` bots, hltv-api. 31 GB RAM. |
| `rpi` | .10 | Ubuntu 24.04 (RPi 4) | **DNS only — a network appliance.** Pi-hole (DNS; **DHCP is the router's** since Sept 2026); Dozzle agent `:7007`; ARM64 CI runner. **2 containers, and it stays that way** — see runbook 10 for the four-part test before adding anything. Boots from a **USB SSD** (the microSD died 2026-09-08). |
| `noblenumbat` | .6 | Ubuntu 24.04 | **Media.** Jellyfin `:8096`, Kavita `:5000`, *arr stack, qBittorrent/SABnzbd/Prowlarr behind Gluetun VPN, Portainer `:9000`. **Uptime Kuma `:3001`** (host network; moved off opti 2026-09-10 so it watches opti from outside). **ntfy `:2586`** — the homelab's phone push server (2026-09-24; off opti for the same reason). ~17 containers. YAMS compose at `/opt/yams/`. |
| `android` | .54 | Termux | Galaxy S10. llama.cpp `:8080` (local LLM). **Intermittent — often offline.** |

Single points of failure worth knowing before you touch anything: **rpi** is the only DNS server
(DHCP now comes from the router), and **opti** now carries storage, the control plane *and* the
app tier — so an opti outage costs the dashboard, the vault and the bots at once, while the LAN
keeps resolving names. That split is deliberate: DNS lives on the cheap always-on box precisely
so rebooting opti is routine. opti's pool is a **single disk with no redundancy**, and its boot
disk is a 40k-hour Seagate ST500DM002 (`sdb` since 2026-09-10 — device letters on opti are NOT
stable) with 272 reallocated sectors, creeping ~8 every two months (256 Jun → 264 Jul 15 → 272
Sep 14); pending/uncorrectable both still 0 — watch those two, not the reallocated count;
runbook 10 has the thresholds. It holds only the OS: app data (`/srv/docker` = `red/docker-apps`)
and homelab.db live on the pool, so its death costs a reinstall, not data. **Peter knows and has
accepted this risk** (acknowledged in Pertal 2026-09-27): don't raise the reallocated count or the
sda one in reports, reminders or audits. Mention the boot disk only if pending/uncorrectable go
non-zero, reallocated jumps by 20+ at once, or SMART overall-health fails.

**Canonical hostnames** (2026-09-10): the dashboard is **`webapp.lan`** — `webapp.rpi.lan` still
resolves as a SAN/alias but is misleading and should not be used in new work. Bare `webapp` does
not resolve; single-label names need a DNS suffix most clients here don't set.

## SSH keys — two separate regimes

Do not mix these up; it is the most common wasted-token rediscovery.

1. **Interactive (you, from the workstation)** — `~/.ssh/config` carries the aliases on both
   boots, so just `ssh opti` either way. Keys differ per side:
   - **tux (Linux):** `~/.ssh/homelab` for all four aliases. android is the odd one:
     **port 8022, user `u0_a204`**. `~/.claude/opti_key` also reaches `ptm@192.168.1.11`.
   - **ptm (Windows):** `~/.ssh/optiplex_omv`, `~/.ssh/rpi`, `~/.ssh/noblenumbat` (config
     added 2026-09-24). **No android key on this side.** Use PowerShell or Git Bash's `ssh`;
     Git Bash here has no coreutils (`ls`/`cat` missing).
2. **Collectors/runners (on opti, fanning out)** — `~/.ssh/hl_agents`, selected via `HL_SSH_KEY`
   with targets in `HL_HOSTS`, both set in `/etc/hl-agents.env`. This key is *not* the
   interactive one.

Passwordless `sudo` works non-interactively on opti, rpi and noblenumbat. Android is unrooted —
privileged commands need adb over localhost.

## Where the repo lives

As of 2026-09-08 the working copy is **`E:\REPO\ptm4` on the Windows side (`ptm`) of this
workstation** (local NTFS disk, not a network share). Edit there. From a tux session the
same disk may be mounted, but check `git status` before assuming it's the same checkout.

The old `/home/ptm/opti/ptm/repo/ptm4` CIFS mount described in earlier revisions of this file
is stale: it was backed by opti's pool checkout, which Peter moved to
`/srv/red/fs/ptm/old repo location/ptm4` on opti (main @ f4175b2, **98 uncommitted modified
files — never `rm -rf` or reset it**, Peter reconciles it by hand). Sessions that treated the
pool copy as the working copy, or the tux CIFS mount as an edit path, were both wrong — treat
any clone reachable from `tux` or opti as a deploy/runtime copy only.

opti's own services (`hl-agent-dispatcher`, `homelab-db`, the webapp `/workspace` mount) run
from `/srv/red/fs/ptm/repo/ptm4/homelab/`. That is **not** a git checkout:
`.github/workflows/opti-deploy.yml` `rsync -a --delete`s its runner checkout there on every
push — a `.git`-less deploy snapshot. Never edit it; a change to opti's services goes live
only when Peter pushes. (Restored and running as of 2026-09-24; runbook 10 §0.1 has history.)

The old `noblenumbat:~/code/ptm4` clone **no longer exists** (reverted 2026-07-22). Do not send
edits there.

`homelab/agentic/` **is tracked in git** (verified 2026-07-25 — only `.claude/` is ignored, per
`.gitignore:54`). Everything in `.claude/` is a generated copy, rebuildable with
`probe.py --wire claude`, so nothing unique lives there. The residual risk is ordinary:
*uncommitted* new files exist only on disk.

## Never do these

Each of these is also blocked by the `PreToolUse` guard (see `../harness/README.md`), so you
will get a hard denial rather than a warning.

- **Never `rm -rf` a ptm4 working copy** on a clean-`git status` basis. Run
  `git status --ignored --porcelain` / `git clean -ndx` first and preserve what they list.
  `git status` hides ignored *and* uncommitted content; this exact mistake destroyed skills and
  rules on 2026-07-22, back when `homelab/agentic/` was still ignored.
- **Never hand-edit Samba or OMV config on opti.** OpenMediaVault regenerates it; edits vanish.
- **Never edit `discord-*` bot files directly on opti.** Bots are managed through the webapp.
- **Never edit `/srv/docker/compose/webapp/` on opti as the fix.** That is a deploy target, not
  the source — the next CI run (`opti-apps-deploy.yml`) reverts it. Edit
  `homelab/hosts/opti/apps/webapp.v3.Fable/` in the repo — the live app since 2026-09-10.
  `webapp.v2.legacy/` and `webapp.v3.Astra/` are undeployed.
- **Never `git commit`, `amend`, `reset`, or push.** Peter commits his own work. Make the change
  and say what needs committing. (The `doc-builder` agent's post-commit docs commit is the one
  sanctioned exception — Peter set it up and it only runs after *his* commits.)
- **Never enable DHCP in Pi-hole.** Since Sept 2026 the router (TP-Link Archer) is the DHCP
  server; two DHCP servers race and present as "all the servers are down".

## Ask the database before you probe

opti runs **homelab-db** (`:9100`), a queryable index of everything the homelab already
knows: every collector report back to June 2026, host inventory, container change history,
and full-text search over every runbook and rule. A session in this repo gets it as the
`homelab` MCP server (see `.mcp.json`).

- `hl_search_docs` — **try this first for any "how does X work here" question.** The
  answer is usually already written in a runbook.
- `hl_status` — current health in one call. `hl_host <host>` — everything about one box.
- `hl_changes` — what containers/mounts changed, and when. `hl_metrics` — long-range trends.
- `hl_query` + `hl_schema` — read-only SQL for anything else.

If the tools aren't present, `HL_DB_TOKEN` is probably not set where Claude Code was launched —
on `ptm` it's a Windows *user* environment variable (set 2026-09-24; the app must be restarted
to see it), on tux it must be exported in the shell. A missing token shows up as "400 Bad
request syntax" in older server builds, 401 in newer ones. Falling back to SSH is fine — but
check here first; it is faster and does not touch a live host. Details: `runbooks/09-homelab-db.md`.

## Collectors and alerts

The collectors (homelab-doctor, network-report every 30 min; hardware, software,
journald-hunter, persistence-auditor daily) run on opti as `hl-collector@<name>.service`
from systemd timers, not GitHub Actions (since 2026-09-24). Logs:
`journalctl -u 'hl-collector@*'`. Alerts go to ntfy (`homelab/tools/notify.py`, topic
`homelab`): a failed unit pages via `OnFailure=`, and each ingest cycle pages *new* critical
findings and stale feeds, once, plus a "resolved" when they clear. To alert from new code,
`from notify import notify` — never build a second channel.

## Working conventions

- Read-only investigation (status, logs, `df`, `docker ps`) needs no approval — just run it.
  State-changing commands: say what you're about to do in one line, then do it.
- Host access goes through the `homelab-ssh` skill rather than hand-rolled ssh invocations.
- Adding anything to the dashboard goes through the `add-to-webapp` skill (board cards:
  `add-webapp-widget`).
- The webapp's frontend is a Vite build shipped by CI on opti — there is no live-on-copy path;
  a change reaches `webapp.lan` only once Peter commits and pushes.
