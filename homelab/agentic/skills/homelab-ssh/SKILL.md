---
name: homelab-ssh
description: SSH into a homelab server (opti, rpi, noblenumbat, or android) to run commands, check status, or make changes on that box. Use whenever a query names one of these hosts and doing anything about it requires actually logging in (not just reading about it in docs).
---

# SSH into a homelab server

Generic lookup + connect procedure. Contains no keys, passwords, or other secrets —
just where to find them and how to use them.

## 1. Resolve the host

The homelab has four reachable nodes, addressable by SSH alias (preferred) or `.lan`
hostname. The authoritative, up-to-date list is
[`homelab/agentic/runbooks/01-hosts-and-ssh.md`](../../runbooks/01-hosts-and-ssh.md) —
re-check it if a name or role doesn't match what's below:

| Alias | Role |
|---|---|
| `opti` | Storage/NAS (ZFS pool `red` → Samba `\\opti\red`; OMV UI-only), CI runner, control plane, and (since 2026-09-10) the app tier — dashboard, vault, notes, bots |
| `rpi` | DNS only (Pi-hole) — a network appliance; DHCP is the router's |
| `noblenumbat` | Media stack (Jellyfin/*arr apps) — the repo clone there was deleted 2026-07-22 |
| `android` | Phone (Termux), SSH on a **non-default port** — check the runbook for the current port and connect string, it changes across reboots |

## 2. Find the key

All aliases are pre-configured in `~/.ssh/config`, but the key differs per side of the
workstation: on **tux** (Linux) it's the shared key `~/.ssh/homelab` for all aliases; on
**ptm** (Windows) it's per-host — `~/.ssh/optiplex_omv`, `~/.ssh/rpi`, `~/.ssh/noblenumbat`,
and **no android alias or key** (android is `port 8022`, user `u0_a204`, tux-only). Check the
config first — it's the source of truth for user, port, and identity file per host:

```bash
ssh -G <alias> | grep -i "identityfile\|hostname\|port\|user"
```

If an alias isn't configured yet, don't guess at a path — check the runbook above for
the current key/port for that host, or ask the user. Don't assume one host's key works
on another (they don't all overlap).

## 3. Connect

```bash
ssh <alias>
```

For a one-off command instead of an interactive session:

```bash
ssh <alias> '<command>'
```

Passwordless sudo is expected to work non-interactively on the Linux hosts (opti, rpi,
noblenumbat) — confirm on the runbook if a `sudo` call unexpectedly prompts.

## Before running server-side commands

Per the repo's standing agent rules: read-only investigation (status, logs, `df -h`,
`docker ps`, etc.) needs no approval — just run it. State-changing commands (installs,
config writes, restarts, deletes, anything touching storage) — narrate what you're about
to do in one line, then run it; don't block waiting for a go-ahead unless the target
host/skill says otherwise (e.g. disk-wipe operations still require explicit confirmation).
