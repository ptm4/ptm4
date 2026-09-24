# Network: DHCP / DNS ("servers down")

## Symptom
"The servers are down" / devices can't resolve names / intermittent LAN outages.

## Root cause
A **dual-DHCP race**: the router and Pi-hole are BOTH handing out DHCP leases,
so clients get conflicting gateways/DNS and the network flaps.

The router at 192.168.1.1 is a **TP-Link Archer** (confirmed 2026-07-31 — earlier revisions
said "Verizon router"; that hardware doesn't exist).

## Intended design (since Sept 2026 — inverted from the original)
- **The Archer (192.168.1.1) is the ONLY DHCP server.** 2-hour leases, gateway `.1`, DNS
  `192.168.1.10` (Pi-hole) + `.1`. Moved 2026-09-08 because the SD-card rpi was unstable.
- **Pi-hole (rpi, 192.168.1.10) is DNS only — its DHCP must be OFF.** rpi should hold a
  router reservation for `.10`.
- Before Sept 2026 it was the reverse (Pi-hole DHCP, router DHCP off). Old notes, reports and
  commits saying "never enable router DHCP" describe that earlier design.

## Fix
1. Check Pi-hole's DHCP is disabled (Pi-hole admin → Settings → DHCP). If it got switched on
   (restoring an old config/backup is the likely trigger), turn it off.
2. Confirm the Archer's DHCP server is enabled and hands out Pi-hole as DNS.
3. Renew leases on affected clients (reconnect / `dhclient -r && dhclient`).

## Related
- Pi-hole runs in Docker on rpi; container name `pihole`. Current leases live in the
  Archer's admin UI, not Pi-hole.
- Whitelist a blocked domain: `pihole allow <domain>` (Pi-hole v6).
- If Pi-hole can't bind :53 after a rebuild, suspect systemd-resolved's TCP stub first
  (runbook 10 addendum).
