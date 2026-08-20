# android — Galaxy S10 server (SM-G973U)

The phone at `192.168.1.54` (`ssh android`, port 8022, user `u0_a204`). Runs llama.cpp
(see [06-local-llm.md](06-local-llm.md)) plus sshd/crond under Termux. This runbook covers
the *host*: what the hardware allows, and the reliability stack that keeps an unrooted
Android 12 phone behaving like a server.

## Hardware identity — do not re-litigate reimaging

**SM-G973U, US Snapdragon (SD855 / `msmnile`), Android 12, bootloader rev 9
(`G973USQU9IXE1`).** Investigated 2026-08-19:

- US Snapdragon Samsungs have **permanently locked bootloaders** — no OEM-unlock toggle,
  `sys.oem_unlock_allowed=0`. postmarketOS / LineageOS / rooting are all impossible.
- The paid hardware unlock (afaneh92) only covers S10 bootloader v1–4; this device is v9
  and anti-rollback fuses block downgrading.

So: the OS stays stock and unrooted, forever. All server hardening works within that.
Privileged operations go through **adb over loopback** (wireless debugging), not root.

## Reliability stack (what keeps it reachable)

Layered, from network to process:

1. **DHCP reservation** in Pi-hole: `a2:04:5a:b7:ab:08 → 192.168.1.54` (added 2026-08-19).
   Caveat: that MAC is Android's *per-SSID randomized* MAC. It is stable unless the Wi-Fi
   network is forgotten/re-added — if android suddenly gets a pool address, re-check the
   MAC (`ip addr show wlan0`) against the reservation (Pi-hole `dhcp.hosts`).
2. **Wake lock + boot script** — `~/.termux/boot/00-start-server.sh` (Termux:Boot) takes
   `termux-wake-lock` and starts runit services: `sshd`, `crond`, `llama`, `llama-ctl`.
3. **Keepalive cron** — `$PREFIX/bin/net-keepalive.sh` every minute: pings the gateway
   (a partial wake lock keeps the CPU up but **not** the radio — the ping is what stops
   doze idling Wi-Fi). After 3 consecutive failures it kicks a scan and, if adb is up,
   bounces Wi-Fi via `svc wifi`. Log: `~/.cache/net-keepalive/log`.
4. **adb self-reconnect** — `$PREFIX/bin/adb-reconnect.sh` every 5 min: tries the cached
   port (`~/.cache/adb-port`), then falls back to a fork-free in-process bash `/dev/tcp`
   sweep of 30000–65535 (~10 min). Pairing keys persist forever; only the *port* rotates
   (on wireless-debugging re-enable/reboot, not while it stays on).
5. **Privileged fixes** — `$PREFIX/bin/apply-android-fixes.sh` (idempotent, run via adb):
   - **Phantom process killer OFF** — Android 12 silently kills Termux children when >32
     exist; this was the historical "llama-server just vanished" cause.
     (`max_phantom_processes` maxed + `settings_enable_monitor_phantom_procs false`,
     pinned against Play-services flag syncs with `set_sync_disabled_for_tests persistent`.)
   - Doze whitelist for com.termux / .api / .boot; `RUN_ANY_IN_BACKGROUND allow`;
     adaptive battery off.
   - Wi-Fi never sleeps (`wifi_sleep_policy 2`), scan throttling off.
   `settings put` values persist across reboots; the deviceidle whitelist does too.

Power: wireless charger, so battery health is the long-term watch item (100%/GOOD as of
2026-08-19; check `termux-battery-status` occasionally — sustained 100% + heat is what
kills phone batteries).

## adb: loopback ONLY — hard-learned 2026-08-19

Do not attempt adb to this phone from another LAN host; it cannot work on this network:

- The Archer router **does not forward mDNS across the wired↔Wi-Fi boundary**, and every
  server is wired — so `adb mdns` discovery finds nothing, ever.
- Cross-network `adb connect` TCP-connects but hangs `offline` (TLS handshake never
  completes), and the connect port **rotates on every Developer-options interaction**,
  making manual port-reading a losing race. Ubuntu/Debian *packaged* adb is additionally
  broken for wireless debugging (no `pair` on Debian 12's 29.x; no working mDNS on 34.x).
- Android SYN rate-limiting blinds external `nmap` after a few sweeps.

From the phone itself (`localhost`), pairing and connecting work first try. Port
discovery on-device: `/proc/net/tcp` is SELinux-blocked and Termux's adb lacks mDNS —
the in-process bash `/dev/tcp` sweep in `adb-reconnect.sh` is the method that works.
(noblenumbat also holds a valid pairing, official platform-tools in `/tmp/ptools` —
ephemeral, and useless anyway per the above.)

## After a reboot (the one manual step)

Wireless debugging **turns itself off on reboot**. Termux:Boot restores everything else
(services, wake lock, cron). To restore the adb layer:

1. On the phone: Settings → Developer options → **Wireless debugging** → ON. Then stop
   touching the screen (interactions rotate the port).
2. Connection is automatic within ~15 min (`adb-reconnect.sh` cron sweeps for the new
   port). **No pairing code needed** — pairing keys survive reboots.
3. Re-pairing is only needed after a factory reset / "revoke debugging authorizations":
   Wireless debugging → **Pair device with pairing code**, then on the phone:
   `adb pair localhost:<pairing-port> <code>`.
4. Re-run `apply-android-fixes.sh` — cheap, idempotent, and re-asserts anything a system
   update may have reset.

## Quick health check

```sh
ssh android 'uptime; sv status $PREFIX/var/service/*; adb devices | tail -2;
             tail -5 ~/.cache/net-keepalive/log 2>/dev/null; termux-battery-status'
```

Healthy = all services `run`, adb shows `localhost:<port> device`, keepalive log quiet.
The phone being unreachable is *expected* to be rare now; if it recurs, check (in order)
DHCP lease/MAC drift, then the keepalive log after it returns, then phantom-process
settings (a Play-services sync can revert `device_config` if the pin was lost).

## Incident log

- **2026-08-19 — phantom-killer massacre (pre-fix), full recovery.** With the killer
  still active, runsvdir/sshd/crond were all killed (SSH `connection refused`; orphaned
  llama-server/llama-ctl survived and `llama-ctl :8081/status` was the only diagnostic
  window — its `sv_status` field proved runsv was dead). Recovery: power-menu restart;
  Termux:Boot brought everything back in ~2 min. Same day: fixes applied and verified
  (`max_phantom_processes=2147483647`, monitor off, sync pinned). Notable: the July doze
  whitelist had silently vanished — `dumpsys deviceidle whitelist` said "Added", not
  already-present. If services ever vanish again with the fixes in place, suspect a flag
  re-sync and re-run `apply-android-fixes.sh`.
