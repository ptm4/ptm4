# Homelab context — read nothing else first

This file is auto-loaded every session. It exists so you never have to grep for hosts, keys,
or "where does the repo live". If a fact you need is missing here, add it here.

Deeper detail lives in `homelab/agentic/runbooks/`. Live per-host facts (containers, ports,
mounts, timers) are regenerated nightly into `homelab/agentic/generated/` — prefer those over
probing a host yourself.

## Hosts

LAN is `192.168.1.0/24`, gateway `.1` (a **TP-Link Archer** — earlier docs said "Verizon
router"; that hardware doesn't exist, confirmed 2026-07-31). All four hosts are SSH-able by alias.

| Alias | IP | OS | Role — what it contains |
|---|---|---|---|
| `tux` | .3 | CachyOS | **You are usually here.** Workstation. No services; nothing depends on it. |
| `opti` | .11 | Debian 12 | **Storage + control plane + app tier.** ZFS pool `red` (4 TB WD Red Plus) exported as Samba `\\opti\red` = `/srv/red/fs` (share config: `/etc/homelab/samba-red.conf`, NOT OMV's smb.conf); old mergerfs pair = weekly cold copy at `/srv/attic`; OMV for UI/monitoring only; agent dispatcher `:9099`; **homelab-db `:9100`** (queryable index + MCP); x86 CI runner; xrdp `:3389`. **Since 2026-09-10 also the whole app tier** (14 containers in `/srv/docker/compose`): dashboard **`webapp.lan:8443`**, Vaultwarden `bitwarden.rpi.lan:443`, notes `:3002`, Uptime Kuma `:3001`, Dozzle `:9999`, 5 `discord-*` bots, hltv-api. 31 GB RAM. |
| `rpi` | .10 | Ubuntu 24.04 (RPi 4) | **DNS only — a network appliance.** Pi-hole (DNS; **DHCP is the router's** since Sept 2026); Dozzle agent `:7007`; ARM64 CI runner. **2 containers, and it stays that way** — see runbook 10 for the four-part test before adding anything. Boots from a **USB SSD** (the microSD died 2026-09-08). |
| `noblenumbat` | .6 | Ubuntu 24.04 | **Media.** Jellyfin `:8096`, Kavita `:5000`, *arr stack, qBittorrent/SABnzbd/Prowlarr behind Gluetun VPN, Portainer `:9000`. ~13 containers. YAMS compose at `/opt/yams/`. |
| `android` | .54 | Termux | Galaxy S10. llama.cpp `:8080` (local LLM). **Intermittent — often offline.** |

Single points of failure worth knowing before you touch anything: **rpi** is the only DNS server
(DHCP now comes from the router), and **opti** now carries storage, the control plane *and* the
app tier — so an opti outage costs the dashboard, the vault and the bots at once, while the LAN
keeps resolving names. That split is deliberate: DNS lives on the cheap always-on box precisely
so rebooting opti is routine. opti's pool is a **single disk with no redundancy**, and its boot
disk is a 40k-hour drive with 264 reallocated sectors (pending/uncorrectable both still 0 — watch
those two, not the reallocated count; runbook 10 has the thresholds).

**Canonical hostnames** (2026-09-10): the dashboard is **`webapp.lan`** — `webapp.rpi.lan` still
resolves as a SAN/alias but is misleading and should not be used in new work. Bare `webapp` does
not resolve; single-label names need a DNS suffix most clients here don't set.

## SSH keys — two separate regimes

Do not mix these up; it is the most common wasted-token rediscovery.

1. **Interactive (you, from tux)** — `~/.ssh/homelab`, already wired in `~/.ssh/config` for all
   four aliases. Just `ssh opti`. android is the odd one: **port 8022, user `u0_a204`**.
   `~/.claude/opti_key` also reaches `ptm@192.168.1.11`.
2. **Collectors/runners (on opti, fanning out)** — `~/.ssh/hl_agents`, selected via `HL_SSH_KEY`
   with targets in `HL_HOSTS`, both set in `/etc/hl-agents.env`. This key is *not* the
   interactive one.

Passwordless `sudo` works non-interactively on opti, rpi and noblenumbat. Android is unrooted —
privileged commands need adb over localhost.

## Where the repo lives

As of 2026-09-08 the working copy is **`E:\REPO\ptm4` on the Windows side of this
workstation** (local NTFS disk, not a network share). Edit there.

The old `/home/ptm/opti/ptm/repo/ptm4` CIFS mount described in earlier revisions of this file
is stale: it was backed by opti's pool checkout, which Peter moved to
`/srv/red/fs/ptm/old repo location/ptm4` on opti (main @ f4175b2, **98 uncommitted modified
files — never `rm -rf` or reset it**, Peter reconciles it by hand). Sessions that treated the
pool copy as the working copy, or the tux CIFS mount as an edit path, were both wrong — treat
any clone reachable from `tux` or opti as a deploy/runtime copy only.

opti's own services (`hl-agent-dispatcher`, `homelab-db`, the webapp `/workspace` mount) still
hardcode the old `/srv/red/fs/ptm/repo/ptm4` path and are broken until it's restored (dispatcher
crash-looping, homelab-db will fail on next restart). Fix is **not** a repoint to `E:\REPO\ptm4`
(opti/Linux can't reach that as a local path) and deliberately **not** a second git checkout on
opti either — `.github/workflows/opti-deploy.yml` now `rsync -a --delete`s its own ephemeral
runner checkout into `/srv/red/fs/ptm/repo/ptm4/homelab/` on every push, a plain `.git`-less
snapshot nobody edits. See `homelab/agentic/runbooks/10-rpi-rebuild-and-app-tier-migration.md`
§0.1 / Phase 2.3 — that step still needs one push (or `workflow_dispatch`) to actually run.

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
- **Never edit `discord-*` files directly on rpi.** Bots are managed through the webapp.
- **Never edit `/srv/docker/compose/webapp/` on rpi as the fix.** That is a deploy target, not
  the source — the next CI run reverts it. Edit `homelab/hosts/rpi/webapp.v2.legacy/` in the
  repo (the live v2 app; `webapp.v3.Fable/` and `webapp.v3.Astra/` are undeployed rewrites).
- **Never `git commit`, `amend`, `reset`, or push.** Peter commits his own work. Make the change
  and say what needs committing.
- **Never enable DHCP on the router (TP-Link Archer).** It races Pi-hole and presents as "all
  the servers are down".

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

If the tools aren't present, `HL_DB_TOKEN` is probably not exported in the shell that
launched Claude Code. Falling back to SSH is fine — but check here first; it is faster and
does not touch a live host. Details: `runbooks/09-homelab-db.md`.

## Working conventions

- Read-only investigation (status, logs, `df`, `docker ps`) needs no approval — just run it.
  State-changing commands: say what you're about to do in one line, then do it.
- Host access goes through the `homelab-ssh` skill rather than hand-rolled ssh invocations.
- Adding anything to the dashboard goes through the `add-to-rpi-webapp` skill.
- The webapp's `frontend/` is bind-mounted on rpi, so static files go live on copy — but a
  change only *persists* once committed and pushed.
