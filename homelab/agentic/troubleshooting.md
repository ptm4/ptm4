# Known agent-report false positives

Findings from the homelab agents that look like real problems but aren't — kept here so
nobody re-investigates them from scratch. If a finding here stops matching reality (e.g.
after code changes elsewhere), update or remove the entry.

---

## network-report: `[android] No default gateway configured` (critical)

**Status: root cause identified and fixed in code 2026-07-22. Not yet deployed/verified
live — see caveat at the bottom.**

### Symptom
`network-latest.json` flagged android with `severity: critical` — `"gateway": null,
"gateway_reachable": false` — while the same report row showed `"internet": true` and
successful DNS lookups (`github.com`, `webapp.rpi.lan` both resolved). Internet clearly
worked; the finding didn't match reality.

### Root cause
`default_gateway()` in `homelab/Tools/homelab/network-report.py` ran `ip route show
default` over SSH and looked for a line starting with `default`. That works on the three
Linux hosts, but **Android routes per-app/per-uid through tables that aren't in the main
routing table an unprivileged process (Termux, unrooted) can see** — so the command
legitimately returns nothing on android even though the OS is routing packets fine
underneath. `routes(host)` (`ip route show`, no `default` filter) confirmed this: android
only showed a local `192.168.1.0/24 dev wlan0` link route, no default line at all — not
because there's no route, but because it's invisible from this vantage point.

### Fix
`default_gateway()` now falls back to `ip route get 1.1.1.1` when `ip route show default`
comes back empty, and parses the `via <gateway>` out of that instead. `ip route get` asks
the kernel what it would actually use to reach a destination — a read-only query, not a
privileged operation — so it works even under Android's per-uid routing and correctly
reports the real gateway (`192.168.1.1`) android's already using.

Verified the parse logic against `ip route get 1.1.1.1` output on a normal Linux host
(`1.1.1.1 via 192.168.1.1 dev <iface> src ... uid 1000`) — same iproute2 output format
Android/Termux's `ip` produces.

### Where
`homelab/Tools/homelab/network-report.py`, `default_gateway()`.

### ⚠️ Caveat — not deployed, and android is currently unreachable anyway
This fix lives only in the working tree here (never committed by me — see the
never-commit rule). It takes effect once pushed to `main` and the next scheduled/manual
`network-report` run picks it up on opti's checkout (opti's self-hosted runner re-checks
out `main` on every `homelab-agents.yml` trigger).

I tried to verify it live by dispatching a fresh run (`POST /api/agents/network-report/run`
via the webapp) with the *old*, unfixed code still deployed, as a baseline — and got a
**different, worse result**: all three critical findings fired (gateway, internet, *and*
DNS), not just gateway. Checked directly from the LAN: `ping 192.168.1.54` and
`192.168.1.126` (the other IP it's been seen at, per
`homelab/agentic/runbooks/01-hosts-and-ssh.md`) both got 100% packet loss, TCP 8022 was
closed, and its ARP entry was `STALE`. **android is not answering on the LAN right now** —
screen off / Wi-Fi asleep / Doze, not a routing or detection problem. That's a real,
separate condition this fix does not address.

So: two things are true at once. (1) The original snapshot that motivated this fix (taken
earlier the same day) showed android reachable with `internet: true` + working DNS but
`gateway: null` — a genuine detection gap, now fixed in code. (2) As of this check, android
is fully off the LAN, which will independently produce all-critical findings regardless of
the gateway fix. Don't treat the next `network-report` run as a clean verification unless
android is confirmed awake and reachable first (`ping 192.168.1.54`, or check
`~/xfer_status.txt`-style liveness from the phone side).
