# Homelab context — read nothing else first

This file is auto-loaded every session. It exists so you never have to grep for hosts, keys,
or "where does the repo live". If a fact you need is missing here, add it here.

Deeper detail lives in `homelab/agentic/runbooks/`. Live per-host facts (containers, ports,
mounts, timers) are regenerated nightly into `homelab/agentic/generated/` — prefer those over
probing a host yourself.

## Hosts

LAN is `192.168.1.0/24`, gateway `.1`. All four hosts are SSH-able by alias.

| Alias | IP | OS | Role — what it contains |
|---|---|---|---|
| `tux` | .3 | CachyOS | **You are usually here.** Workstation. No services; nothing depends on it. |
| `opti` | .11 | Debian 12 | **Storage + control plane.** ZFS pool `red` (4 TB WD Red Plus) exported as Samba `\\opti\red` = `/srv/red/fs` (share config: `/etc/homelab/samba-red.conf`, NOT OMV's smb.conf); old mergerfs pair = weekly cold copy at `/srv/attic`; OMV for UI/monitoring only; agent dispatcher `:9099`; x86 CI runner; xrdp `:3389`. |
| `rpi` | .10 | Ubuntu 22.04 (RPi 4) | **DNS + web.** Pi-hole (DNS *and* DHCP for the whole LAN); dashboard webapp `:8443`; Vaultwarden `:443`; notes `:3002`; 5 `discord-*` bots; ARM64 CI runner. ~12 containers. |
| `noblenumbat` | .6 | Ubuntu 24.04 | **Media.** Jellyfin `:8096`, Kavita `:5000`, *arr stack, qBittorrent/SABnzbd/Prowlarr behind Gluetun VPN, Portainer `:9000`. ~13 containers. YAMS compose at `/opt/yams/`. |
| `android` | .54 | Termux | Galaxy S10. llama.cpp `:8080` (local LLM). **Intermittent — often offline.** |

Single points of failure worth knowing before you touch anything: **rpi** is the only DNS/DHCP
server (and boots from an SD card), and **opti** backs every other host's storage over CIFS.

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

`/home/ptm/opti/ptm/repo/ptm4` on tux **is a CIFS mount of opti's pool**. Saving a file here
writes straight to opti's disk — there is no separate copy to sync.

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
  the source — the next CI run reverts it. Edit `homelab/hosts/rpi/webapp/` in the repo.
- **Never `git commit`, `amend`, `reset`, or push.** Peter commits his own work. Make the change
  and say what needs committing.
- **Never enable DHCP on the Verizon router.** It races Pi-hole and presents as "all the servers
  are down".

## Working conventions

- Read-only investigation (status, logs, `df`, `docker ps`) needs no approval — just run it.
  State-changing commands: say what you're about to do in one line, then do it.
- Host access goes through the `homelab-ssh` skill rather than hand-rolled ssh invocations.
- Adding anything to the dashboard goes through the `add-to-rpi-webapp` skill.
- The webapp's `frontend/` is bind-mounted on rpi, so static files go live on copy — but a
  change only *persists* once committed and pushed.
