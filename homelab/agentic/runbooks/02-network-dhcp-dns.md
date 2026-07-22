# Network: DHCP / DNS ("servers down")

## Symptom
"The servers are down" / devices can't resolve names / intermittent LAN outages.

## Root cause
A **dual-DHCP race**: the Verizon router and Pi-hole are BOTH handing out DHCP leases,
so clients get conflicting gateways/DNS and the network flaps.

## Intended design
- **Pi-hole (rpi, 192.168.1.10) is the ONLY DHCP + DNS server.**
- The **Verizon router's DHCP must be OFF.**

## Fix
1. Log into the Verizon router and confirm its DHCP server is disabled. If it re-enabled
   itself (firmware update, factory event), turn it back off — this is the usual trigger.
2. Confirm Pi-hole DHCP is active (Pi-hole admin → Settings → DHCP).
3. Renew leases on affected clients (reconnect Wi-Fi / `dhclient -r && dhclient`).

## Related
- Pi-hole runs in Docker on rpi; container name `pihole`. Leases:
  `docker exec pihole cat /etc/pihole/dhcp.leases`.
- Whitelist a blocked domain: `pihole allow <domain>` (Pi-hole v6).
