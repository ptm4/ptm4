# Opti → Proxmox VE migration plan

*Drafted 2026-08-24. Status: PLAN — nothing executed. Peter buys hardware, then we schedule the cutover.*

## Why now

- **sda is dying.** SMART reallocated sectors grew 256 → 264 since June (flagged critical by
  homelab-db daily). sda is the boot disk. An OS reinstall is coming whether we want one or
  not — so the reinstall might as well be a hypervisor.
- **The pool makes this cheap.** ZFS pool `red` lives entirely on sdc and is self-describing:
  `zpool export` → reinstall OS on a different disk → `zpool import` and every dataset and
  snapshot is intact. No data copy involved.
- **Proxmox VE is Debian with native ZFS.** The host stays a Debian system (PVE 9.x = Debian 13
  base), so every Python service currently on opti can run on the host or in a Debian LXC
  unchanged.
- **Payoff:** VM capacity for the things Debian-on-bare-metal can't do — first target is a
  Windows Server VM for the pwsh/Windows experiments discussed 2026-08-24.

## Current state (verified 2026-08-24 via dmidecode/lsblk/systemctl)

**Hardware:** Dell OptiPlex (board 0GY6Y8, i5-3570, 4 DIMM slots, max 32GB DDR3).
Currently 6GB installed as 2GB (DIMM1) + 4GB (DIMM2); DIMM3/DIMM4 empty.

| Disk | Model | Size | Contents | Fate |
|---|---|---|---|---|
| sda | ST500DM002 (**dying**) | 466G | ext4 root (330G used = OS + attic branch `/srv/sda-pool`) + swap | **Retire.** Keep on a shelf unwiped = full rollback image |
| sdb | Hitachi HTS5475 | 596G | NTFS, attic branch (ro), 3 realloc sectors stable | Keep as-is |
| sdc | WD40EFZZ (WD Red Plus) | 3.6T | ZFS pool `red` (690G alloc, 18%) | **Untouched** — export/import only |
| sr0 | optical | — | — | candidate to vacate a SATA port/bay if needed |

**Services to carry over** (unit inventory taken 2026-08-24):

| Unit(s) | What | Config/data lives at |
|---|---|---|
| `smbd` + `/etc/homelab/samba-red.conf` | Samba share `[red]` → `/srv/red/fs` — **the SPOF, restore first** | `/etc/homelab/`, smbpasswd db (`pdbedit -L`, tdbsam in `/var/lib/samba/`) |
| `homelab-db.service`, `-vitals`, `-ingest.timer` | homelab-db :9100 API/MCP | SQLite on pool (`red/opsdb`) — survives; unit files in repo `homelab/hosts/opti/systemd/` |
| `hl-agent-dispatcher.service` | dispatcher :9099 | repo + `/etc/hl-agents.env` (**secrets — back up by hand**) |
| `hl-arch-agent.service` | architecture agent | repo |
| `actions.runner.ptm4-ptm4.opti.service` | GitHub x86 runner | `/home/ptm/actions-runner` — **cannot be tarball-restored; re-register with a fresh token** |
| `homelab-docs/-agentic-docs/-autoupdate/-autoreboot/-coldcopy/opti-health-digest` timers | nightly jobs | repo + unit files |
| `zfs-scrub-monthly@red.timer` | pool scrub | trivial re-enable |
| `pod-filebrowser` / `container-filebrowser-app` | podman filebrowser | podman unit files; low value — decide keep/drop |
| `xrdp` | remote desktop :3389 | superseded by PVE web UI :8006; reinstall only if missed |
| OMV (web UI :80) | monitoring only since 2026-07-25 | **dies here, deliberately — do not reinstall** |
| SSH keys | `~/.ssh/hl_agents` (collector fan-out), `authorized_keys` | back up by hand |
| Homelab CA | `certs/ca` | on the pool — verify path pre-cutover, survives automatically |

## Phase 0 — hardware (Peter buys)

1. **RAM: 4x8GB DDR3-1600 (PC3-12800) non-ECC unbuffered UDIMM, 240-pin desktop, 1.5V**
   (1.35V DDR3L also works on this board). Replaces both existing sticks; all four slots
   populated → 32GB.
   ⚠️ The B&H kit considered on 2026-08-24 (Crucial CT2K16G4SFRA32A) is **DDR4 SODIMM laptop
   memory — incompatible twice over.** See pricing section below.
2. **Boot SSD: 1TB SATA 2.5"** (~$50–60, e.g. Crucial MX500/BX500, WD Blue, Samsung 870 EVO).
   1TB and not 500GB because it also replaces sda's attic branch (see Phase 3.5).
   Check a free SATA port + bay first; the optical drive's port/bay is the fallback.
3. Optional but smart: a SATA data+power cable check before cutover day.

## Phase 1 — pre-cutover (opti still on Debian, no downtime)

1. **Commit and push everything.** The working copy lives on the pool (safe), but the repo is
   the service-rebuild source — uncommitted skills/rules/webapp work must be on GitHub before
   cutover. (2026-07-22 lesson.)
2. **Config tarball** to the pool AND to a second location (tux or rpi):
   `/etc/homelab/`, `/etc/hl-agents.env`, `/etc/fstab`, `/etc/systemd/system/*.service|*.timer`
   (the non-repo ones), `/var/lib/samba/` (tdbsam), `~/.ssh/` (both keys + authorized_keys +
   config), `~/.claude/` if present, podman unit files, `/etc/exports` if any, crontabs,
   `dpkg --get-selections` output, `ip a` + `/etc/network/interfaces` or NM profiles.
3. **Verify the attic cold copy is fresh** (last run Sun 04:05) — it's the second copy of pool
   data during the risky window.
4. **`zfs snapshot -r red@pre-proxmox`** — free, instant rollback point for the data itself.
5. Verify Homelab CA location on the pool; note Pi-hole has DHCP reservations but opti is
   static — record current IP config (static .11, gw .1, DNS .10).
6. Grab a fresh GitHub runner removal+registration token ready (Settings → Actions → Runners).
7. Announce downtime to yourself: **everything that mounts \\opti\red goes stale** — tux repo
   working copy, noblenumbat media mounts, rpi mounts. Plan the cutover when nothing critical
   (CI, coldcopy, media playback) is mid-flight.

## Phase 2 — cutover day

1. Stop services in order: runner → dispatcher/arch-agent → homelab-db → smbd. Let the fleet's
   CIFS mounts go stale; they recover in Phase 4.
2. `zpool export red` (clean export = clean import; belt-and-braces given step 1.4's snapshot).
3. Power off. **Install RAM (4x8GB), install new SSD, physically disconnect sda** — do not
   wipe it; it's the rollback: plug it back in and the old Debian boots exactly as before.
4. Boot Proxmox VE 9.x installer (USB). Target: **the new SSD only** — the installer's disk
   picker is the single most dangerous screen of this whole plan; sdb and sdc must not be
   selected. ext4 or ZFS-on-root on the SSD both fine; ext4 is simpler for a single disk.
5. First boot: static IP 192.168.1.11, gw .1, DNS 192.168.1.10, hostname `opti`. PVE web UI
   at `https://192.168.1.11:8006`.
6. `zpool import red` (add `-f` only if the export in step 2 was skipped/unclean). Verify
   `zfs list` shows all datasets and `/srv/red/fs` content.
7. Set ARC cap: with 32GB, `options zfs zfs_arc_max=8589934592` (8GB) in
   `/etc/modprobe.d/zfs.conf` → leaves ~20GB for VMs/LXCs.
8. Restore samba immediately (`apt install samba`, drop in `/etc/homelab/samba-red.conf`
   include, restore tdbsam) — this un-breaks the whole fleet's storage before anything else.

**Abort path at any point before step 4 completes: reconnect sda, boot, done.**

## Phase 3 — service rebuild

Recommended shape: **storage plane on the PVE host, control plane in one Debian 13 LXC**
(`opti-core`), pool datasets bind-mounted into it. Rationale: samba/ZFS want to be on the
host (no virtualization tax on the SPOF); the Python services get isolation, snapshots, and
easy rebuild without touching the host. A lazier-but-valid first pass is everything on the
host (it's still Debian) and containerize later — decide by appetite on the day.

1. Host: samba (done in 2.8), zfs-scrub timer, smartd/smartmontools.
2. `opti-core` LXC (Debian 13, 2 vCPU, 4GB, bind-mounts: `/srv/red/fs`, `red/opsdb`,
   agent-logs): clone ptm4 repo, restore `/etc/hl-agents.env`, hl_agents SSH key, then
   homelab-db + vitals + ingest, dispatcher, arch-agent, docs/digest/autoupdate timers.
   **Static IP or DHCP reservation for the LXC** — collectors and the MCP server bind :9100/:9099;
   simplest is to keep them reachable at 192.168.1.11 via the host (LXC on a different IP means
   updating `.mcp.json` token URL, rpi webapp agent endpoints, and collector env). Decide:
   same-IP-on-host vs new-IP-LXC. *Default: run homelab-db + dispatcher on the HOST for now so
   :9100/:9099 stay at .11, move into LXC as a later cleanup.*
3. GitHub runner: re-register fresh in the LXC or on host (`config.sh` with new token, same
   labels), confirm rpi-deploy / collector workflows pick it up.
4. coldcopy + attic: see 3.5. autoreboot timer: re-evaluate — PVE hosts shouldn't blind-reboot
   weekly with VMs running; keep disabled until VMs have proper shutdown ordering.
5. **attic rebuild (3.5):** old attic = mergerfs(sda-branch + sdb-ntfs). sda leaves. Create
   `/srv/ssd-attic` on the 1TB boot SSD, re-point mergerfs to `ssd-attic:sdb`, re-enable
   `homelab-coldcopy.timer`, run one manual coldcopy to reseed. (Pool alloc is 690G; branch
   capacity ~1.4T combined — fits.)
6. filebrowser: reinstall in LXC if actually used, else drop and note in runbook.

## Phase 4 — fleet fallout + verification

Known blast radius (all previously observed, see memory/runbooks):

- **noblenumbat**: stale CIFS handles after opti storage changes — running containers coast
  until recreated, then fail. Fix: umount + automount re-trigger (nn-deploy has the preflight).
  Do it proactively, then `docker ps` sweep.
- **tux**: remount `/home/ptm/opti` (this very working copy).
- **rpi**: webapp agent endpoints + any opti mounts; verify dashboard's opti tile goes green.
- Verify in order: `zpool status red` → smb from tux → `hl_status` (proves :9100 + ingest) →
  dispatcher run-now of one collector → runner picks a job → coldcopy manual run → PVE UI.
- Watch homelab-db findings for 48h — it's the thing that will notice what we forgot.

## Phase 5 — the payoff (post-migration, unhurried)

- Windows Server 2025 eval VM (8GB RAM, 60GB on SSD, virtio drivers) — the pwsh/Windows lab
  discussed 2026-08-24. Eval license runs 180 days, rearm-able.
- PVE backup jobs (vzdump) for the LXC/VMs onto the pool.
- Optional later: mirror the pool (second 4TB into `red` as mirror vdev) — the standing
  `opti-drive-onboard` skill already covers this.
- Update runbooks + `01-homelab-context.md` host table (opti role becomes "PVE hypervisor +
  storage"), re-run `probe.py --wire claude`.

## RAM pricing research (2026-08-24)

Target part: 4x8GB DDR3-1600 (PC3-12800) non-ECC unbuffered UDIMM, CL9–CL11, 1.5V or 1.35V
DDR3L. Registered/ECC server pulls (PC3-12800**R**) will NOT post on this board — a common
trap in eBay results.

| Source | Option | Config | Price for 32GB | Notes |
|---|---|---|---|---|
| **Newegg** | **Timetec 75TT16NUL2R8-8GK4** | 4x8GB DDR3L-1600 CL11 | **$72.99 shipped** | Best new price. Marketplace (sold by Timetec, top-rated, lifetime warranty). [newegg.com/p/0RN-00A3-001K9](https://www.newegg.com/p/0RN-00A3-001K9) |
| Newegg | A-Tech NE-SS-0628 | 4x8GB DDR3-1600 CL11 | $84.32 | Marketplace, direct from A-Tech |
| Newegg | NEMIX MD12800-828LK04-517 | 4x8GB DDR3-1600 CL11 | $87.89 | Claims Samsung/Micron/Hynix chips |
| Newegg | Crucial Ballistix Sport | 4x8GB DDR3-1600 **CL9** | ~$87–114 | Legacy stock, price varies by seller |
| **Micro Center Westbury** | **Patriot Viper 3 PV316G160C0K** ×2 | 2×(2x8GB) DDR3-1600 **CL10** | **$131.98** | **Only 2 kits in stock**, in-store pickup only — the whole desktop-DDR3 shelf there is otherwise bare. SKU 437418 |
| **B&H** | Patriot Signature PSD38G16002 ×4 | 4×(1x8GB) DDR3-1600 | $107.96 | In stock, orderable, free ship. Best mail-order name-brand option. Most other B&H DDR3 is discontinued |
| eBay (floor) | used TeamGroup/A-Tech/generic kits | 4x8GB DDR3(L)-1600 | ~$45–55 shipped | Absolute floor if used is OK; verify UDIMM non-ECC before buying |
| Amazon (ref) | same Timetec kit | 4x8GB | ~$81 | Newegg beats it |

**Recommendation:** Timetec 4x8GB on Newegg at $72.99 — matched kit, right spec (DDR3L runs
fine at 1.35V on this board), lifetime warranty, best new price. If you're near Westbury
anyway, the Patriot Viper CL10 kits are the nicest silicon of the bunch but nearly double the
cost for margin-of-error latency gains on an Ivy Bridge. eBay used at ~$50 is defensible for
a lab box; avoid anything marked RDIMM/ECC/registered.

Note: the B&H Crucial CT2K16G4SFRA32A kit originally considered is DDR4-3200 **SODIMM**
(laptop) — incompatible with this board on both generation and form factor.

## Hardware decision (added 2026-08-24 — SUPERSEDES Phase 0 until Peter picks)

**Hold the DDR3 purchase.** Researched three paths for "opti as multi-VM centerpiece"; a
fourth emerged that beats them all. Whichever box wins, Phases 1–5 apply unchanged — sdc
(pool) moves into the new box, `zpool import`, same service rebuild, same rollback via
untouched sda.

Market context that drives everything: **DDR4 spiked 50–100% in 2025–26** (used 2x16GB ≈
$120, new ≈ $250), so machines sold *with* 32GB carry pre-spike RAM in their price and
dominate DIY value.

**CORRECTION 2026-08-24 (same day):** the first version of this table recommended the 7070
MT at "$174.88" — that was eBay multi-variation bait pricing (the price of the i3-9100/8GB
base config; the title advertises the top config). Verified in-browser: **i7-9700/32GB runs
$374.88 (128GB SSD) to $459.88 (1TB SSD)** on that listing. Ranking corrected below.

| Path | Cost | vs i7-3770 multi | Verdict |
|---|---|---|---|
| A. Upgrade 7010 in place (i7-3770 + 32GB DDR3 + SSD) | ~$140 | 1.0x (baseline) | The budget floor, and at real market prices no longer embarrassing — 40% the cost of the next rung. Still capped by the 2012 platform |
| B. eBay 7080 Micro i7-10700T 16GB ([227424342252](https://www.ebay.com/itm/227424342252), $238.50, Grade B, no OS/PSU adapter) | ~$260 + RAM later | 2.1x | **Disqualified for this role: 1L Micro = no 3.5" bay.** The 4TB pool drive would hang off USB — bad for ZFS. Fine box, wrong job |
| C. Gut the 7010 case, new board inside | n/a | — | **Dead.** Fixed (riveted) rear I/O panel, partially-standard standoffs, proprietary 6-pin front-panel needing a splice — hours of Dremel work to save the $60–80 a real case costs |
| **C'. DIY new build: Ryzen 5 5600 + B550M + 32GB used DDR4 + case/PSU** | **~$360** | **3.4x** | **Best performance + standard-parts-forever** (any AM4 CPU to a 5950X, DDR4 to 128GB, any case/PSU). 5700X drop-in later = 4.1x. RAM spike hurts but every 32GB option pays it somewhere |
| ~~D.~~ Refurb OptiPlex 7070 MT i7-9700/32GB ([236943477939](https://www.ebay.com/itm/236943477939)) | ~~$174.88~~ **$374.88–459.88** | 2.1x | **Corrected price kills it**: more money than C' for 60% of the performance, on a proprietary-ish platform |
| **D'. Refurb Precision 3630 Tower: i7-8700, 16GB, 256GB NVMe** ([ebay 147276498260](https://www.ebay.com/itm/147276498260), $274.99 OBO, verified single-config listing, last one) | **$275** (+~$120 used 2x16GB later) | 2.1x | **Best centerpiece per dollar at real prices.** Workstation board: 128GB DDR4 ceiling, ECC via Xeon swap, 2x 3.5" bays + M.2, 460W-class PSU, full-height PCIe. Start on 16GB (ARC 4GB + Win VM 8GB + LXCs fits), add RAM when it pinches |

**Corrected recommendation: D' (Precision 3630, $275) for a buy-it-done centerpiece — or C'
(Ryzen DIY, ~$360) if building it yourself and never touching Dell-proprietary again appeals
more.** D' spreads the RAM spend (usable at 16GB today, 32–128GB whenever), has the highest
ceiling of any option, and holds pool + attic drives internally. B stays disqualified on the
3.5"-bay constraint regardless of price. A remains the honest budget answer if $275 feels
like too much box for the job.

Whichever wins: the 7010 retires (or becomes a cold-attic shelf box), Phase 0 becomes "buy
the machine", the attic branch lands in the second 3.5" bay, and the DDR3 purchase is
cancelled (Path A only).

## The build (Path C' chosen by Peter, 2026-08-24) — parts list + price tracker

Peter picked the DIY build. Researched parts (live prices 2026-08-24), all tracked
automatically — see the tracker below.

| Part | Pick | Today | Buy at | Notes |
|---|---|---|---|---|
| CPU | Ryzen 5 5600 (Newegg, no cooler) | $116.99 | ≤$105 | 5700X $158.99 (buy ≤$145) is the +2-core option |
| Mobo | ASRock B550M Pro4 | $89.99 | ≤$80 | **6x SATA — the ZFS pick.** Budget alt: Gigabyte B550M K $69.99 (4x SATA) |
| RAM | 2x16GB DDR4-3200 | $179–210 new | **≤$120–130** | **SPIKED 2-4x** (AI/HBM wafer shift); used floor ~$120 on eBay (watch manually — see below) |
| PSU | ASRock PRO-650G 650W Gold ATX 3.1 | $49.99 | ≤$45 | MSI A650GL modular $79.99 (≤$70) for quality |
| NVMe | 1TB Gen4 (P400 Lite / NV3 / SN770) | $150–168 | **≤$120** | **spiked ~2x** vs 2024; buy instantly under $100 |
| Cooler | Thermalright AX120 R SE | $17.90 | ≤$16 | stable; overkill-quiet for 65W |
| Case | see below | $128–172 | — | |

**Total today ≈ $525 (with cheap case ≈ $655); patient-buyer target ≈ $445 + case.**
CPU/board/PSU/cooler prices are normal — patience pays there. RAM and NVMe are the spiked
categories and still rising; those buy-thresholds are buy-NOW signals whenever they fire.

**Case picks** (Peter wanted a black cube; ranked for cube-looks + drive cooling + quiet):

1. **Jonsbo N4 — $128** — black cube + walnut strip, native mATX, 6x 3.5" (4 hot-swap);
   add one 120mm fan to the drive chamber. The literal thing described.
2. **Fractal Node 804 — $134.99** — the classic mATX NAS cube: dual-chamber, 8x 3.5",
   dedicated quiet drive-cooling out of the box. The zero-mods safe pick.
3. **Jonsbo N6 — $172 pre-order (ships ~Aug 30)** — Feb 2026 release, 9x 3.5" hot-swap
   trays, fixes every N3/N4 review complaint. The future-proof pick.

**Price tracker (live since 2026-08-24):**

- `homelab/tools/pricewatch/` — collector + `items.json` (16 items, targets = the buy-at
  column). Runs on opti 4x/day (`homelab-pricewatch.timer`, 01/07/13/19:24 + jitter).
- Report → `agent-logs/pricewatch-latest.json` (with embedded 180-day history);
  homelab-db ingests it into the **`price_history`** table (schema migration v3) and
  raises a **warn finding** when an item hits its target OR drops ≥10% under its 30-day
  median — surfaced via `hl_status` and the webapp notifications.
- Webapp: `GET /api/pricewatch` route + **"Price watch" board widget** (sparklines, green
  "buy" pill at target; category filter in widget settings). Ships on next commit+push
  (Vite build via rpi-deploy).
- Trend queries: `SELECT day, price FROM price_history WHERE item='ram-2x16-teamgroup-amazon' ORDER BY day` via `hl_query`.
- **Known limits:** eBay 403s all server-side fetchers (TLS fingerprint — same as hltv;
  would need the OAuth Browse API), so the ~$120 used-RAM floor is watched manually.
  Newegg prices come from the embedded product JSON (list − instant rebate — the visible
  multi-variation "headline price" is bait, verified the hard way).

## Open decisions for Peter

1. RAM purchase (see pricing) and 1TB SSD purchase.
2. Control plane on host vs LXC on day one (plan defaults: :9100/:9099 services on host,
   LXC later).
3. Keep or drop filebrowser and xrdp.
4. autoreboot timer future on a hypervisor.
