# Homelab hosts & SSH

> Core facts (host table, both key regimes, repo location) live in
> [`../rules/01-homelab-context.md`](../rules/01-homelab-context.md), which is auto-loaded every
> session. This runbook is the deeper reference — read it when the summary isn't enough.
>
> Live per-host detail (containers, ports, mounts, timers) is regenerated nightly into
> [`../generated/`](../generated/) by the architecture agent. Prefer that over re-probing.

## Hosts

LAN `192.168.1.0/24`, gateway `192.168.1.1` (Verizon router — its DHCP must stay **off**).

### tux — 192.168.1.3
The workstation, and where Claude Code normally runs. CachyOS. Runs no homelab services and
nothing depends on it. Mounts opti's Samba share at `~/opti` (CIFS 3.1.1), which is how the repo
is reached. Also `ptm.lan` / `tux.lan` in Pi-hole.

### opti — 192.168.1.11
Storage and control plane. Debian 12, Intel i5-3570, 5.7 GiB RAM.
- **OpenMediaVault** manages the box; web UI on `:80`. **Never hand-edit the Samba config** —
  OMV regenerates it.
- **mergerfs pool** at `/srv/pool` (~1.1 TB, two branch disks, the large one NTFS via fuseblk),
  exported as `\\opti\fs`. Everything else in the homelab mounts this.
- **Agent dispatcher** on `:9099` (`hl-agent-dispatcher.service`) — enable/disable + run-now for
  the runners, driven by the webapp.
- Self-hosted **x86 CI runner** (`actions.runner.ptm4-ptm4.opti`), xrdp on `:3389`.
- SSH: `ssh opti` (user `ptm`, `~/.ssh/homelab`). Also reachable with `~/.claude/opti_key`.

### rpi — 192.168.1.10
DNS, DHCP and the web tier. Ubuntu 22.04 on a Raspberry Pi 4, 3.7 GiB RAM, **117 GB SD card** —
the most fragile hardware here, carrying the most critical role.
- **Pi-hole v6** in Docker: DNS *and* DHCP for the whole LAN, ~15 local A records, 6 MAC-pinned
  reservations. Whitelist a domain with `pihole allow <domain>`.
- **Dashboard webapp** behind nginx TLS on `:8443` (`webapp.rpi.lan`), **Vaultwarden** on `:443`
  (`bitwarden.rpi.lan`), **notes** on `:3002`.
- **Discord bot fleet** — 5 containers (`discord-weather`, `-healthdigest`, `-jellyfin`,
  `-sports`, `-hltv`). Their control APIs bind `:8080` on the internal Docker network only, so
  **manage them via the webapp, never by editing files on the rpi**.
- Self-hosted **ARM64 CI runner** — this is what deploys the webapp.
- Mounts opti at `/mnt/opti-fs`; the webapp container sees `/agent-logs`, `/reports` and
  `/workspace` read-only through it.
- SSH: `ssh rpi` (user `ptm`, `~/.ssh/homelab`).

### noblenumbat — 192.168.1.6
Media stack. Ubuntu 24.04, Intel i7-8665U, 16 GB. A Dell Latitude 7400 laptop with sleep masked;
its real failure mode is **thermal**, not software (the whole-host outage on 2026-07-16 was a
cooling problem, not Jellyfin).
- **Jellyfin** `:8096` (HW transcode via `/dev/dri/renderD128`), **Kavita** `:5000`.
- *arr stack: Sonarr `:8989`, Radarr `:7878`, Lidarr `:8686`, Bazarr `:6767`.
- Behind **Gluetun** VPN (`network_mode: service:gluetun`, so they share its netns and lose all
  connectivity with it — an intentional kill-switch): qBittorrent, SABnzbd, Prowlarr `:9696`,
  Mylar3 `:8090`, FlareSolverr `:8191`. Portainer on `:9000`.
- Media lives on **opti**, not locally: `/mnt/opti-library`, `/mnt/opti-shows`, `/mnt/opti-media`.
- Compose at `/opt/yams/docker-compose.yaml`. A `watchtower` service is defined there but is not
  currently running.
- SSH: `ssh noblenumbat` (user `ptm`, `~/.ssh/homelab`).

### android — 192.168.1.54
Galaxy S10 (SM-G973U), unrooted, Termux. Runs the local llama.cpp server on `:8080` (Qwen2.5-3B)
— see the local-LLM runbook. **Frequently offline**; treat it as intermittent and let callers
degrade gracefully.
- SSH: `ssh android` — **port 8022, user `u0_a204`**, `~/.ssh/homelab`.
- Unrooted, so privileged commands go through adb over localhost.
- Wi-Fi MAC randomization makes the lease bounce (seen at `.54` and `.126`). Pi-hole has a
  record for `.54`; if it drifts, either pin a DHCP reservation (after disabling MAC
  randomization for the home SSID) or rely on `android.lan`.

## Keys — two regimes, don't mix them

**1. Interactive** (from tux, i.e. you). Shared key `~/.ssh/homelab`, wired in `~/.ssh/config`
for all four aliases, so `ssh <alias>` just works. Verify what an alias resolves to:

```bash
ssh -G <alias> | grep -iE '^(hostname|port|user|identityfile) '
```

`~/.claude/opti_key` is a second, persistent key for `ptm@192.168.1.11`.

**2. Collectors / runners** (on opti, fanning out to every host). A *different* key,
`~/.ssh/hl_agents`, selected by `HL_SSH_KEY`, with targets in `HL_HOSTS`
(`opti=127.0.0.1,rpi=192.168.1.10,noblenumbat=192.168.1.6` by default) — both set in
`/etc/hl-agents.env`. The runners reach opti *over SSH to itself* so every host takes one
uniform code path. See `homelab/Tools/homelab/_hosts.py`.

If a runner reports every host unreachable at once, suspect this key rather than the network.

## Access notes

- Passwordless `sudo` works non-interactively on opti, rpi and noblenumbat.
- **No inbound access to this LAN.** WireGuard and its peer-manager UI are decommissioned — no
  `wg0`, nothing on UDP 51820 — though orphaned peer configs and a `vpn.rpi.lan` DNS record
  survive. Remote access is LAN-only: SSH everywhere, RDP on opti (xrdp) and noblenumbat
  (gnome-remote-desktop).
- Both CI runners poll GitHub **outbound**, which is why deploys work with no exposed port.

## The repo

`/home/ptm/opti/ptm/repo/ptm4` on tux is a CIFS mount of opti's pool — a save writes to opti's
disk directly. There is no second copy to keep in sync.

**The `noblenumbat:~/code/ptm4` clone was deleted (2026-07-22).** Revisions of this runbook
before 2026-07-25 called it the primary copy and told you to edit there instead of the "stale
opti mount". That was wrong and following it sends you to a path that no longer exists.

`homelab/agentic/` **is** tracked in git (only `.claude/` is ignored, and that is entirely
generated by `probe.py --wire claude`). Still, before deleting any working copy run
`git status --ignored --porcelain` / `git clean -ndx` and preserve what they list — a clean
`git status` hides ignored *and* uncommitted files, which is how the 2026-07-22 loss happened.
