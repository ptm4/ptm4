# Homelab hosts & SSH

## Hosts
- **opti** — main server, 192.168.1.11. Big storage: mergerfs pool at `/srv/pool` (OMV-managed). SSH: `ssh opti` (user ptm, homelab key).
- **rpi** — Raspberry Pi, 192.168.1.10. Runs **Pi-hole v6 in Docker** (DNS + DHCP for the LAN) and the **Discord bot fleet**. SSH: `ssh rpi` (user ptm, homelab key). Pi-hole whitelist: `pihole allow <domain>`.
- **noblenumbat** — media + code server. Runs Jellyfin / Radarr / Sonarr. Also holds the **primary copy of the ptm4 repo** at `noblenumbat:~/code/ptm4` (edit there, not the stale opti mount). SSH: `ssh noblenumbat`.
- **android** — Galaxy S10 (SM-G973U), unrooted, Termux. 192.168.1.x (DHCP, hostname `android` / `android.lan`). SSH: `ssh android` (port **8022**, user u0_a204, homelab key). Runs the local LLM server (see local-llm runbook).

## Keys
- Most hosts: `~/.ssh/homelab`.
- opti also reachable via a persistent key at `~/.claude/opti_key` for ptm@192.168.1.11.

## Note on the phone's IP
Android Wi-Fi MAC randomization makes the DHCP lease bounce (seen at .54 and .126). For a
stable address either pin a Pi-hole DHCP reservation (after disabling MAC randomization for
the home SSID on the phone) or rely on `android.lan` hostname resolution.
