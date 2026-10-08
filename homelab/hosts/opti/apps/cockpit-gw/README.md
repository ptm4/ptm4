# Cockpit inside Pertal

Three gateways run on opti in compose profile `cockpit`. Each Ubuntu 24.04 image pins
`cockpit-ws=362-1~bpo24.04.1`, cross-connects its `--local-session=-` stream to an SSH
forced command `sudo -n /usr/local/libexec/pertal-cockpit-bridge` on one patched host, and serves a
shared **root session without a login**. The existing authenticated host `:9090`
listeners are retained. All trusted LAN/WireGuard users of Pertal get full root control.
Cockpit operations bypass Pertal jobs, confirmations, maintenance holds and audit
records; use host journals/Cockpit evidence. Pertal no longer offers `host.reboot` or
its ZFS precheck. The Console retains the opti ZFS and noblenumbat POST cautions.

## Trust and availability

Only nginx and Pertal share `172.30.90.0/24` with the gateways. Gateways publish no
ports, join no app network, and cannot resolve app service names. They need outbound
SSH to the three LAN hosts, so this bridge is not marked Docker `internal: true`.
No nginx startup dependency waits for a gateway. DNS resolution is lazy.
Nginx checks actual client IPs against LAN/WireGuard, exact allowed Origins and
`Sec-Fetch-Site: cross-site`. It does not trust supplied forwarding headers for access.
Host headers retain the port and proxy requests retain the full URI.

The dedicated private key stays root-only on opti in `/etc/pertal-cockpit/`; the mount
is read-only. Host public keys come through already trusted workstation SSH aliases,
not `ssh-keyscan`. Authorization preserves all other keys, rejects a conflicting
entry and disables forwarding, PTY, user rc and agent forwarding with `restrict`.
The gateway supervisor cleans both children on signals/failure, exits for Docker
restart after either exits or two bounded manifest failures. HTTP 200 login HTML is
unhealthy. Logout ends the shared bridge and temporarily interrupts all tabs on that
host; the restarted gateway restores root access automatically.

## Host setup (from the trusted workstation)

```powershell
python homelab/hosts/opti/apps/cockpit-gw/setup/setup.py --packages
```

Requires existing trusted `opti`, `rpi`, `noblenumbat` SSH aliases for ptm, passwordless
sudo, Docker on opti and the hosts' existing backport apt sources. Package patching
precedes key authorization. Repeating setup reuses the dedicated key, verifies
restricted entries, migrates the exact legacy bridge entry, and skips correct package versions/existing network/firewall rules.
Without `--packages`, it refuses authorization until the exact approved host page
packages are installed. Only opti needs the gateway-subnet UFW SSH allowance: remote
hosts see opti's masqueraded LAN address and already accept that trusted connection.

Ubuntu hosts upgrade installed Cockpit modules to `362-1~bpo24.04.1` with
`--no-remove` after simulation, saving prior packages/configuration/dependency versions.
For opti, `setup/Bookworm.Dockerfile` builds Debian's security-fixed
`337-1+deb13u2` source as `337-1~bpo12+pertal1` in an isolated Bookworm image. Source
tarball SHA256s are checked; Debian's shipped-JavaScript patch and its zgrep check
remain in `debian/rules`. Build tests run as an unprivileged builder, without `nocheck`.
Install only after dependency simulation; preserve previous packages/configuration.
[Debian security tracker](https://security-tracker.debian.org/tracker/CVE-2026-4802).

After syncing/building the gateway context on opti, run for each host:

```bash
docker build -t pertal-cockpit-gw:362 cockpit-gw
bash cockpit-gw/setup/spike.sh opti
bash cockpit-gw/setup/spike.sh rpi
bash cockpit-gw/setup/spike.sh noblenumbat
```

Before a new rollout, this loopback-only spike must pass: require shell
and valid manifests, WebSocket `id -u=0`, repeated session-bus failures followed by
system/internal D-Bus calls and live metrics, logout restart, SSH-loss restart, and clean
SIGTERM. A failed gate stops rollout; do not switch architecture.

## Bridge compatibility repair (2026-10-04)

Cockpit 337/362's vendored `Bus.default_user()` caches a Bus before connecting.
These root SSH sessions have no user-session bus. The first request fails cleanly;
a second reuses the empty cached pointer and raises `sd_bus_attach_event: Invalid
argument` outside channel error handling. A page retry then produces `channel is
already open`, terminating the shared bridge and causing nginx 502s during restart.
This was reproduced through the loopback gateway; manifest/root-only checks missed it.

`setup/bridge_compat.py` is installed as the root-owned, non-writable launcher
`/usr/local/libexec/pertal-cockpit-bridge`. It resets a newly populated default-bus
cache if creation/attachment raises `OSError`, then propagates the original error.
Existing healthy shared buses are retained. It invokes the normal Cockpit bridge;
package files, pinned versions, native authenticated `:9090`, access restrictions
and gateway architecture stay intact. A missing root user bus can still emit a
nonfatal browser warning. Noblenumbat's PCP metrics passed after gateway restart;
no PCP package change was required.

Run `python setup/setup.py` from this gateway directory to install/migrate an existing
setup (without package upgrades), then run each isolated spike. Restart only the
three `cockpit-<host>` containers to adopt the launcher. Setup checks the approved
host package versions first; conflicting/duplicate dedicated key entries fail untouched.
Authorization backups are saved before migration; newer launcher revisions are
backed up under `/var/backups/pertal-cockpit/bridge-compat/`.

To roll back only this repair, replace the exact dedicated key line's forced command
with `sudo -n /usr/bin/cockpit-bridge`, keeping `restrict` and the same key. Preserve
other keys, then restart only that gateway. The original crash can recur. The launcher
can remain unused; removing it is optional once no key references it. Do not downgrade
the security-fixed Cockpit packages for this repair.

## Deployment

Peter commits/pushes. CI syncs the gateway build context before validating compose
with both `pertal` and `cockpit` profiles. `setup/nginx-preflight.sh` tests the staged
candidate with the deployed nginx image, certificates and app network before copying
into the deployed bind-mounted inode. Pertal builds/starts first; gateway builds and
container starts then must pass. An offline host may leave its gateway unhealthy and
restarting without failing deployment. Configuration/build/start failures fail CI.
Each built image runs `--check-config` against its compose environment and key mount
without opening SSH before starting, so invalid configuration fails even when hosts
are offline.

`PERTAL_COCKPIT=1` registers 60-second, 5-second-timeout snapshots, stale after five
minutes. `GET /api/console` reads memory only. Disabled/loading/failed/stale hosts
have no iframe. Last host defaults to opti; only configured hosts and relative paths
are accepted. URL queries/hashes are ignored; internal navigation state may carry a
validated deep-link hash. Theme uses Cockpit's `shell:style` storage hook. The worker
bypasses every `/cp-` request so root pages cannot replace the offline app shell.

## Rollback

1. Stop/remove only the three gateways:
   `docker compose --profile cockpit stop cockpit-opti cockpit-rpi cockpit-noblenumbat`
   and `docker compose --profile cockpit rm -f cockpit-opti cockpit-rpi cockpit-noblenumbat`.
2. Restore `/srv/docker/compose/nginx-wg.conf.before-cockpit` and
   `docker-compose.yml.before-cockpit` into their original files. Test nginx first;
   recreate only nginx/Pertal as needed to detach the gateway network, with
   `PERTAL_COCKPIT` removed/disabled. Never `docker compose down` the whole app tier.
   CI backups are per deployment; preserve the pre-feature copy before later pushes.
3. Remove only the authorized_keys line matching the dedicated key's blob on each
   host, or restore its `.before-pertal-cockpit-*` backup if no later keys were added.
   Keep the key/config directory root-only for investigation/rollback; remove it only
   when access has been revoked everywhere.
4. Remove only `ufw allow from 172.30.90.0/24 to any port 22 proto tcp` on opti via
   `sudo ufw delete allow from 172.30.90.0/24 to any port 22 proto tcp`.
   Remove `compose_cockpit_gw` only after all attached services are detached.
5. Each host's `/var/backups/pertal-cockpit/<UTC>/` has `installed.txt`,
   `simulation.txt`, prior `.deb` files and the pre-upgrade Cockpit configuration.
   Simulate `sudo apt-get --allow-downgrades --no-remove -s install <saved .deb files>`;
   inspect, then install the same list with `-y`. Restore saved `/etc/cockpit/` contents
   and restart `cockpit.socket`. Downgrade restores the old security exposure, so
   revoke the shared-root key and disable gateways first. Backups contain host configs:
   keep them root-only. Existing normal SSH and authenticated Cockpit access remain.

## Checks and acceptance

`python -m unittest -v test_gateway.py`, Pertal backend tests, zero-error/warning Svelte
checks, frontend build, both compose profiles, candidate `nginx -t`, trial images.
After Peter's push: all three root consoles and Terminal identity, desktop/375px,
theme, recovery, clean browser console, worker shell integrity, and a reversible
test-service operation. Require foreign-Origin/cross-site rejection, sibling proxy
denial, isolated gateway DNS/network and no published gateway listener. Record local
checks, host setup, deployment, live browser verification and Peter acceptance separately.
