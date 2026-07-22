# VPN: gluetun port-forward failure

## Symptom
Torrent/downloads stall; no incoming connections; the forwarded port on the VPN stops
working even though the VPN tunnel itself looks up.

## Root cause
gluetun's **NAT-PMP port forward dies silently** — the tunnel stays connected but the
forwarded port is lost, so nothing tells you until throughput drops.

## Fix / current state
- This is **auto-healed** by the **`vpn-stack-heal` watchdog** (running since 2026-07-11).
  It detects the dead port-forward and re-establishes it without manual action.
- Check watchdog status: `cat /var/lib/vpn-stack-heal/status.json`.
- If it's genuinely stuck, restart the VPN stack container(s) and re-check the status file.

## Don't
Don't assume "VPN down" — the tunnel is usually fine; it's specifically the port-forward.
Check the status.json first.
