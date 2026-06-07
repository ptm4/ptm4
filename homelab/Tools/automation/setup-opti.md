# Opti agent host — one-time setup

The homelab agents run **on the opti server** (192.168.1.11, OpenMediaVault), scheduled by
GitHub Actions on a self-hosted runner and controlled from the webapp via a small dispatcher
service. The desktop is never involved. Everything below is reboot-persistent.

Share root on opti: `/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs` (the Pi mounts this as
`/mnt/opti-fs`; the webapp sees `/reports` + `/agent-logs`).

---

## 1. Self-hosted GitHub Actions runner (as a service)

Download the runner from GitHub → repo **Settings → Actions → Runners → New self-hosted runner**,
then in the `actions-runner` dir:

```bash
# Register unattended, labeled 'opti' (registration token is short-lived ~1h)
./config.sh --url https://github.com/ptm4/ptm4 \
  --token <REGISTRATION_TOKEN> \
  --name opti --labels opti --unattended --replace

# Install + start as a systemd service (auto-starts on every boot)
sudo ./svc.sh install ptm
sudo ./svc.sh start
sudo ./svc.sh status        # expect: active (running)
```

The `opti` label is what isolates this runner — the agents workflow pins
`runs-on: [self-hosted, opti]`, so it never lands on the Pi, and the Pi's deploy runner is left
untouched.

## 2. Group access for the runner user

The agents need to read all logs and query docker:

```bash
sudo usermod -aG docker,systemd-journal,adm ptm
sudo ./svc.sh stop && sudo ./svc.sh start   # restart runner to pick up new groups
```

## 3. Config + secrets — `/etc/hl-agents.env`

Single source of config, sourced by both the workflow and the dispatcher. Root-owned, `600`:

```bash
sudo tee /etc/hl-agents.env >/dev/null <<'EOF'
HL_REPORTS_DIR=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/security-reports
HL_AGENT_LOGS_DIR=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/agent-logs
HL_DATA_DIR=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/agent-logs/.state
HL_NGINX_LOG=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/logging/stack.log
LEETIFY_API_KEY=your-leetify-developer-key
STEAM64_ID=76561198053334813
HL_DISPATCH_TOKEN=pick-a-long-random-string
# Optional: enables the Claude-written CS2 coaching narrative on top of the
# heuristic Leetify review. Without it you still get the full heuristic report.
ANTHROPIC_API_KEY=sk-ant-...
# Optional: override the review model (default claude-opus-4-8).
# LEETIFY_REVIEW_MODEL=claude-opus-4-8
EOF
sudo chmod 600 /etc/hl-agents.env

mkdir -p /srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/agent-logs
```

## 4. Dispatcher service (enable/disable + run-now)

Edit the `WorkingDirectory`/`ExecStart` paths in `hl-agent-dispatcher.service` if your runner
work dir differs (default: `~/actions-runner/_work/ptm4/ptm4/homelab/Tools/automation`), then:

```bash
sudo cp homelab/Tools/automation/hl-agent-dispatcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hl-agent-dispatcher
systemctl status hl-agent-dispatcher          # expect: active (running) on :9099
```

## 5. Webapp side (on the Pi)

In `/srv/docker/compose/.env` add (token must match step 3):

```
DISPATCHER_URL=http://192.168.1.11:9099
HL_DISPATCH_TOKEN=pick-a-long-random-string
```

A `git push` to `main` triggers `rpi-deploy.yml`, which redeploys the webapp with the new
`/api/agents` route, the `#agents` page, and the enable/disable + run-now buttons.

---

## How it runs

- **Scheduled:** `homelab-agents.yml` — `homelab-doctor` + `network` every 30 min; the rest daily
  at 09:00 UTC. Each agent is skipped if disabled in `agents-state.json`.
- **On demand:** the webapp **Run now** button → backend → dispatcher → agent runs immediately.
- **Enable/Disable:** the webapp toggle → dispatcher writes `agents-state.json`; both the schedule
  and run-now honor it.

> GitHub `schedule` is best-effort (≥5-min, often delayed) and only fires while opti is online —
> fine since opti is always-on. For guaranteed timing, the same agents drop into systemd timers
> (optional `setup-opti-timers.sh`, not built yet).

## Manual test

```bash
# one agent, immediately
set -a; source /etc/hl-agents.env; set +a
python3 homelab/Tools/homelab/network-report.py
ls -la "$HL_AGENT_LOGS_DIR"

# dispatcher
curl -s -H "Authorization: Bearer $HL_DISPATCH_TOKEN" http://192.168.1.11:9099/state | jq
```

## 6. Leetify positional analysis (optional, heavy)

The Leetify agent (`Tools/leetify/leetify-stats.py`) always produces the heuristic +
Claude review. To additionally parse Valve demos for real "where you die" hotspots and
per-spot reposition advice, install the parser and flip the env flag:

```bash
# demoparser2 needs Python >= 3.11. awpy + matplotlib are optional (heatmap PNGs).
python3 -m pip install --user demoparser2
python3 -m pip install --user awpy matplotlib   # optional, for heatmaps

# enable in /etc/hl-agents.env
ANTHROPIC_API_KEY=sk-ant-...          # required for the AI reposition narrative
LEETIFY_PARSE_DEMOS=1                  # turn the demo pipeline on (default off)
# LEETIFY_DEMO_MAX=6                   # matches to parse per run (default 6)
# HL_DEMO_CACHE_DIR=...                # demo cache (default <agent-logs>/.demos)
```

Each run downloads + parses up to `LEETIFY_DEMO_MAX` recent `de_*` demos (tens of MB +
seconds–minutes each), caches them by match id, and writes hotspots into
`leetify-latest.json` (`positions`) plus a "Positional breakdown" section in the report.
If `demoparser2` is missing or `LEETIFY_PARSE_DEMOS` is unset, the step is skipped and the
normal review is unaffected.
