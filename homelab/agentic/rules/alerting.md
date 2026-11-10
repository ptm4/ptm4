# Rule: alert severity and routing

Peter ignored the phone because it was all noise (Nov 2026: 60 pushes in 3 days, every one
the same VPN problem flapping). A push now means "act", and everything else waits for the
digest. Approved 2026-11-10. Implemented in `homelab/tools/homelab-db/ingest.py`
(`route_alerts` / `push_alerts`).

| Severity | Means | Where it goes |
|---|---|---|
| `critical` | Peter must act within hours, or something is lost / at risk | ntfy push **with sound** (priority 4), once per open problem |
| `warn` | look at it this week | **one silent daily digest** (~09:30 local, priority 2) + dashboard / `hl_status`. Never pushes on its own |
| `info` | record only | history only |

Critical examples: pool degraded or ≥90%, a host or DNS down, backups or ingest failing,
a rule-01 boot-disk trigger, an unexpected persistence entry, a cert ≤7 days, a reboot
refused. ntfy priority **5 is reserved for Uptime Kuma host/DNS-down**. "Resolved" never
pushes with sound: a cleared critical gets one silent note (priority 1) and the digest
lists it.

**Damping.** Conditions from the 30-min tools page after ~50 min continuously critical.
Daily tools (journald-hunter, persistence-auditor, hardware-report, software-inventory)
and one-off events page on first sight. Resolved = clear for 2 h. A key that paged does not
page again within 24 h.

**Writing a finding that may alert:**

- Emit a finding (`severity`, `message`) and let ingest route it. **Never call `notify()`
  for a finding**; the unit `OnFailure=` hook (`hl-notify-failure@`) is the one exception.
- The open-problem key is `tool|host|message`, with the message normalised: everything
  after **` | `** is ignored, and digits, IPv4 addresses and quoted values collapse. So put
  volatile detail (minutes, IPs, which step ran) **after ` | `**, and keep the part before
  it stable, or one problem pages as a new one every cycle.
- A critical message says what to do, before the ` | `
  (e.g. `... port forwarding dead for over an hour; check the Proton/WireGuard config | <detail>`).
- Accepted risks are recorded as `decision` entries in `homelab/agentic/incidents.json`, and
  the code reads them: e.g. `opti-boot-disk-risk-accepted` carries `alert_when`.
