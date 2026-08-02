# Known bugs — 2026-07-26 audit (post mission-control overhaul)

Severity-ordered. Line numbers refer to the working tree as of the audit.

## Status — all resolved same day

| # | Resolution |
|---|---|
| B1 | **Fixed** — `GET /api/linkcheck` probes server-side (fixed origin list, self-signed tolerated); frontend paints dots from it |
| B2 | **Fixed** — `escHtml()` on every interpolation in the new panels; `toast()` is text-only unless `allowHtml` |
| B3 | **Accepted as posture** — LAN-trusted like every existing write (samba save, run-now, bot send); recorded in `routes/agents.js` comment. Gate at nginx if the dashboard ever leaves the LAN |
| B4 | **Fixed** — ribbon rollup/freshness only counts runners that have reported; `hltv-watchlist` catalogued as manual in `runners.js` |
| B5 | **Fixed** — 8787 allowlisted; unexpected-port check now ignores loopback-only listeners |
| B6 | **Fixed** — header stamp uses the newest of the three fetched reports |
| B7 | **Fixed** — `/api/trends` carries `pool_name`; the chart shows only the current storage era |
| B8 | **Fixed** — `confirmAction()` refuses to stack a second overlay |
| B9 | **Fixed** — 70s `AbortSignal` on restart fetch (15s on Pi-hole pause) with honest timeout toast |
| B10 | **Fixed** — superseded by B1; internal probes run in parallel |
| B11 | **Fixed** — links filter only auto-focuses on `pointer: fine` devices |
| B12 | **Fixed** — timers surfaced in the Services & upkeep tile; dead `TIMER_RE` removed |
| B13 | **Fixed** — activity sorts on `Date.parse`, not string compare |
| B14 | **Fixed** — filled buttons use `--accent-emphasis` on agents/samba pages |

Three more surfaced (and were fixed) while verifying the above:

| # | Resolution |
|---|---|
| B15 | **Fixed** — inside the webapp container `rpi.lan` resolves to `::1`, so the B1 probes for Pi-hole/Cockpit dialed the container's own loopback and reported them down. Probe entries now carry a `target` (LAN IP) separate from the origin `key` the frontend matches on |
| B16 | **Fixed** — `/api/timers` "passed" parser swallowed the tail of the preceding timestamp (`:05 EDT 20h ago`); now walks duration tokens back from `ago` |
| B17 | **Fixed** — android (a phone, documented intermittent) going to sleep marked the whole network report **critical**, turning the fleet pill red. Its reachability findings are now `warn`; real hosts stay `critical` |

---

## B1 · HIGH — Link-health dots are dead on the real site (mixed content)

**Symptom:** on `https://webapp.rpi.lan:8443/#links`, every `http://` service (17 of
21 links) shows a grey "no answer" dot forever, even though the services are up.

**Cause:** `checkLinkHealth()` (`frontend/app.js:553-575`) fetches `http://` LAN URLs
from a page served over **https**. Browsers block active mixed content (fetch/XHR from
a secure page to an insecure origin) before the request leaves, so the probe always
lands in the catch. The audit that showed "18 green" ran through a plain-http test
proxy, which masked exactly this.

**Fix:** probe server-side. Add `GET /api/linkcheck` to the backend that HEAD/GETs each
URL and returns `{url, up}` — with the target list taken from a server-side copy of the
link inventory (never from the query string, so it can't be used as an SSRF proxy).
Frontend paints dots from that one response. Bonus: fixes B10 (client-side probes are
slow) and lets the three self-signed-https services (Cockpit, Vaultwarden ×2) get real
answers too, since Node can be told to tolerate the LAN CA while a browser can't.

---

## B2 · HIGH — XSS vector: new panels interpolate report text into innerHTML unescaped

**Symptom/risk:** the activity feed renders `${e.message}` raw
(`frontend/app.js:977`); also container tooltip (`:714`), container name/image cells
(`:880-884`), VPN `lastAction`, upkeep/network strings, and `toast()`/`confirmAction()`
bodies. `escHtml()` exists (`app.js:2745`, used ~97× by the older pages) but none of
the new panels call it.

Docker names/images are charset-safe, but **finding messages are not**: journal-hunt
and the security reports echo raw log lines (nginx access logs contain
attacker-controlled request paths), dmesg output, and apt text. A logged request like
`GET /<img src=x onerror=…>` would execute in the dashboard the next time the feed
renders. LAN-only exposure, but the whole point of the feed is to display exactly this
kind of untrusted text.

**Fix:** wrap every interpolated string in the new render paths with `escHtml()` —
`loadActivity`, `loadContainers` (incl. `title=` attributes), `loadUpkeep`,
`loadNetwork`, `loadStorageAndVpn`, `restartError`, `confirmAction` body params, and
make `toast()` escape by default with an explicit opt-out for the few callers that pass
intentional `<b>` markup.

---

## B3 · MEDIUM — Write endpoints are unauthenticated LAN-wide

**Symptom/risk:** `POST /api/agents/:host/restart-container` and
`POST /api/pihole/blocking` accept requests from anything that can reach
`webapp.rpi.lan:8443`. The agent bearer token is attached **by the webapp**
(`backend/routes/agents.js`), and the type-the-name confirm modal is client-side
courtesy only. One `curl` from any LAN device can restart Vaultwarden or pause
ad blocking.

Consistent with the dashboard's existing no-auth posture, but these are its first
write primitives, so the posture is worth a deliberate decision rather than an
inherited one.

**2026-08-02 update (Cockpit tab, agent v0.4.0):** the write surface now includes host
reboot, apt upgrade, allowlisted service restarts and WoL (`/api/agents/:host/{reboot,
apt-upgrade,restart-service,wake}`). This raises the stakes of the accepted posture but
does not change the decision: exposure is still LAN/WireGuard-only, the agents remain
token-gated with hardcoded allowlists and a ZFS reboot guard server-side, and the typed
confirm modal mitigates accidents (not malice — same as before). Re-gate at nginx before
the dashboard is ever reachable beyond the LAN.

**Fix options (pick one):**
1. Accept as trusted-LAN posture; record that decision here and in the techdoc.
2. nginx `location`-level restriction on the two POST paths (basic auth, or
   `allow`-list the couple of client IPs that should drive the dashboard).
3. Frontend sends a shared secret header (prompted once, kept in localStorage);
   backend rejects writes without it. Weakest, but zero infra change.

---

## B4 · MEDIUM — `unknown` runner status renders as a red fleet pill

**Symptom:** the header ribbon maps any status that isn't `ok`/`warn` to the red
`crit` tone (`frontend/app.js:592`). `hltv-watchlist` sits in agent-logs with
`status=unknown, run_at=None` and no CATALOG entry (`backend/routes/runners.js:19`),
so on a day when everything else is `ok` the fleet pill would read **"! unknown"
in red** — an alarm that means nothing. It also pads the freshness strip with
`hltv-watchlist —`.

**Fix:** in `loadRibbon()`, rank `unknown` as neutral (grey pill, "? unknown") and
exclude uncatalogued/manual runners from both the worst-of rollup and the freshness
strip. Separately, give `hltv-watchlist` a CATALOG entry in `runners.js` so it stops
defaulting to a 24 h cadence + permanent stale badge.

---

## B5 · MEDIUM — Collector flags the agents' own port as suspicious, forever

**Symptom:** every network run emits `Unexpected listening port(s): 8787` for all
three hosts (visible ×3 at the top of the activity feed), keeping the network report
permanently at `warn`.

**Cause:** `homelab/tools/collectors/network-report.py:27` — `EXPECTED_PORTS` predates
hl-arch-agent; 8787 was never added. The same run flagged 46675 on noblenumbat, which
is a **loopback-only VS Code remote server** (`code-…`, 127.0.0.1) — transient and
benign.

**Fix:** add `8787` to `EXPECTED_PORTS` with a comment (`hl-arch-agent, all hosts`).
For the 46675 class, stop flagging loopback-only listeners: the collector should
restrict the "unexpected" check to sockets bound on non-loopback addresses
(`listening_detail` already carries the bind address). Do **not** allowlist 46675
itself — it's ephemeral and would be stale tomorrow.

---

## B6 · LOW — Header stamp says "report 8h ago" while the doctor is minutes old

**Cause:** the `#home-generated` badge uses `hardware-latest.run_at`
(`frontend/app.js:654`), and hardware runs **daily** (doctor/network run every 30 min).

**Fix:** stamp with the newest `run_at` across the four reports (they're all already
fetched in `loadHostVitals`), or label it explicitly: `hw report 8h ago`.

---

## B7 · LOW — Pool trend sparkline mixes three storage eras

**Symptom:** the storage tile's 30-day trend hover reads `min 15.9 · avg 63` — it
splices mergerfs-era percentages (~70 %), the short-lived wrong 3 % readings from the
restructure window, and the new zpool numbers into one line, so the average is
meaningless right now.

**Fix (optional, ages out on its own):** `/api/trends` now has `pool_name` in fresh
doctor snapshots; carry it per-point and have the chart break the line (sparkline
already renders nulls as gaps) whenever `pool_name` changes. Old points without a
name count as their own era.

---

## B8 · LOW — Double-click on a restart button stacks two confirm modals

**Cause:** `restartContainer()` (`frontend/app.js` actions block) only disables the ⟳
button after the modal is confirmed; the modal itself doesn't guard against a second
invocation.

**Fix:** module-level `confirmOpen` flag in `confirmAction()` — return `false`
immediately if a modal is already mounted (or disable the clicked button before
`await confirmAction(...)` and restore in `finally`).

---

## B9 · LOW — Restart fetch has no client-side timeout

**Cause:** the backend caps the agent call at 55 s, but the browser fetch in
`restartContainer()` has no `AbortSignal` — if nginx or the network wedges, the sticky
"Restarting…" toast and disabled button persist until the browser's own default gives
up.

**Fix:** `signal: AbortSignal.timeout(70_000)` on the fetch; in the abort branch,
toast "no response after 70s — the restart may still have completed; check the
containers panel."

---

## B10 · LOW — Link health probes run sequentially

**Cause:** `checkLinkHealth()` awaits each of the 21 probes in series with a 3.5 s
timeout — worst case ~70 s to paint the last dot, and the no-cors GETs download full
index pages.

**Fix:** superseded by B1's server-side probe. If B1 is deferred:
`await Promise.allSettled(cards.map(probe))`.

---

## B11 · LOW — Links page auto-focus pops the keyboard on phones

**Cause:** `renderLinks()` calls `input.focus()` unconditionally
(`frontend/app.js:543`) — on mobile this opens the on-screen keyboard over the list on
every visit.

**Fix:** focus only on pointer devices:
`if (matchMedia('(pointer: fine)').matches) input.focus();`

---

## B12 · INFO — `/api/timers` is live but nothing consumes it

The endpoint (`backend/routes/dashboard.js`) parses systemd timers from the agent
fragments and works, but the planned "Scheduled jobs" panel was cut from the final
home grid, leaving dead API surface (plus the unused `TIMER_RE` constant beside it).

**Fix:** either add the panel (natural spot: sp4 tile next to Network, showing
vpn-stack-heal / media-import / autoupdate / coldcopy next+last runs) or remove the
endpoint and constant. Don't leave it undocumented — dead surface invites drift.

---

## B13 · LOW — Activity feed sorts mixed ISO-8601 flavors as strings

**Cause:** `/api/activity` sorts `String(b.ts).localeCompare(String(a.ts))`; coldcopy
stamps `…43Z` while the runners stamp `…43.000+00:00`. String order only breaks when
timestamps tie to the second, but it's still a latent mis-sort.

**Fix:** sort on `Date.parse(ts) || 0` in the backend comparator.

---

## B14 · LOW — Filled buttons use `--accent` as background with white text

**Cause:** `agents/index.html:63` and `samba/index.html:65` style `.btn.primary` as
white-on-`var(--accent)`. Pre-retheme that was a mid blue; the GitHub-dark `--accent`
is `#58a6ff`, and white on `#58a6ff` is ~2.2:1 — fails contrast, looks washed out.

**Fix:** filled controls should use `--accent-emphasis` (`#1f6feb` dark / `#0969da`
light) as the background — that's precisely the token GitHub uses for primary buttons;
white text passes on both. One-line change per page.

---

## Deliberate non-bugs (documented so nobody "fixes" them)

- **Feed items all say "just now" after a run** — findings carry the report's
  `run_at` by design; the tile is labeled "from latest reports".
- **Grey dots on Cockpit/Vaultwarden links** — self-signed https can't be probed from
  the browser at all; the tooltip says so. Becomes solvable server-side with B1.
- **`GET /vitals` on the agents is unauthenticated** — read-only counters on a
  LAN-only listener; `POST /restart` on the same port requires the bearer token and
  refuses to exist without one configured.
- **opti shows 0 containers in the fleet table** — opti genuinely runs no docker;
  its workloads are systemd units.
