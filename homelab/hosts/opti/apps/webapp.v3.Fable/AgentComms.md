

---

## Fable: 2026-09-10 — INCIDENT — "webapp is down" (it wasn't) + a real latent cert bug

**The webapp never went down.** It answered 200 on `https://192.168.1.11:8443` throughout.
What was broken was DNS resolution of `webapp.lan` on Peter's workstation: rpi is the only
resolver, it had just rebooted, and Windows had cached the failure. `Clear-DnsClientCache`
fixed it instantly and it has been 200 by name ever since.

**But diagnosing it surfaced something genuinely broken, and worse than the symptom.**

The TLS certificate had never been reissued after the app-tier migration. It carried:

    CN=webapp.rpi.lan
    SAN: DNS:webapp.rpi.lan, DNS:webapp.rpi, IP:192.168.1.10   <-- rpi's OLD address

It did **not** cover `webapp.lan` — the name `01-homelab-context.md` now calls canonical,
the name I had just written into `/api/health` and the docs — nor opti's `192.168.1.11`,
where the thing actually runs. So every browser hitting the canonical hostname would have
got a certificate error, and the IP was pointing at a host that no longer serves this app.
The Vaultwarden cert HAD been reissued during the migration (2026-09-10 02:32); this one
was simply missed.

Reissued with `tools/certs/issue-cert.sh` off the existing **ptm Homelab CA** — same CA, so
nothing needs re-trusting on any device — as:

    CN=webapp.lan
    SAN: DNS:webapp.lan, DNS:webapp.rpi.lan, DNS:webapp, DNS:webapp.rpi,
         DNS:opti.lan, IP:192.168.1.11
    valid to 2028-12-13

The old pair is backed up in place (`*.bak-2026-09-10`) by the script. File basename kept as
`webapp.rpi.lan.pem` on purpose — that path is bind-mounted in the compose file, and renaming
it would be a second change for no benefit. nginx restarted; browser loads clean, no warning.

**Note for the next person:** `issue-cert.sh`'s header still documents the rpi era —
`CERTS_DIR` defaults to a tux CIFS view and the usage example ends `IP:192.168.1.10`, and it
tells you to `ssh rpi 'docker restart nginx-webapp'`. All three are now wrong. I ran it with
an explicit `CERTS_DIR=/srv/red/fs/ptm/certs` on opti. Worth correcting the script's docs.

**Also:** a stale `rpi: reboot required` incident was showing after rpi had already rebooted.
Not a bug — the alert rules rebuild their hit set from scratch each feed-poller tick, so it
cleared on its own within a minute of the collectors re-running. Open incidents: 0.
