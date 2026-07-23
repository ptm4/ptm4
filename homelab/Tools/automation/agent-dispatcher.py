#!/usr/bin/env python3
"""
agent-dispatcher.py — tiny LAN control plane for the homelab agents, run on opti.

Stdlib-only HTTP daemon (no deps) that lets the webapp enable/disable agents and run
them on demand. It owns agents-state.json (in the agent-logs dir, so the webapp reads
it through its existing read-only mount). Agents are run from an allowlist — never
arbitrary commands. Child processes inherit this daemon's environment, so set the
agent env (HL_REPORTS_DIR, HL_AGENT_LOGS_DIR, LEETIFY_API_KEY, …) via the systemd
EnvironmentFile=/etc/hl-agents.env.

Endpoints (optional bearer auth via $HL_DISPATCH_TOKEN):
  GET  /state                       -> {"agents": {name: {enabled, last_run}}}
  POST /agents/<name>/enabled       body {"enabled": bool}
  POST /agents/<name>/run           -> launches the agent (fire-and-forget)

CLI helper (used by the GitHub Actions workflow to honor enable/disable):
  agent-dispatcher.py --is-enabled <name>   # exit 0 if enabled, 1 if disabled

Env: HL_BIND (default 0.0.0.0), HL_PORT (default 9099), HL_DISPATCH_TOKEN (optional),
     HL_AGENT_LOGS_DIR (state location).
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # homelab/Tools
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(TOOLS_DIR, "..", "..", "agent-logs")
)
STATE_PATH = os.path.join(AGENT_LOGS_DIR, "agents-state.json")
TOKEN = os.environ.get("HL_DISPATCH_TOKEN", "")

# name -> script path (relative to homelab/Tools). The only commands this daemon runs.
AGENTS = {
    "journald-hunter":     os.path.join(TOOLS_DIR, "linux-security", "journald-hunter.py"),
    "persistence-auditor": os.path.join(TOOLS_DIR, "linux-security", "persistence-auditor.py"),
    "hardware-report":     os.path.join(TOOLS_DIR, "homelab", "hardware-report.py"),
    "software-inventory":  os.path.join(TOOLS_DIR, "homelab", "software-inventory.py"),
    "homelab-doctor":      os.path.join(TOOLS_DIR, "homelab", "homelab-doctor.py"),
    "network-report":      os.path.join(TOOLS_DIR, "homelab", "network-report.py"),
    "docs-generator":      os.path.join(TOOLS_DIR, "homelab", "docs-generator.py"),
    "leetify-stats":       os.path.join(TOOLS_DIR, "leetify", "leetify-stats.py"),
    "refresh-cs2-knowledge": os.path.join(TOOLS_DIR, "leetify", "refresh-cs2-knowledge.py"),
}

# Tools whose workspace wiring can be (re)materialized from the webapp via
# probe.py --wire <tool>. Whitelisted so the endpoint can't run arbitrary tools.
PROBE = os.path.join(os.path.dirname(TOOLS_DIR), "agentic", "probe.py")
WIREABLE = {"claude"}

# Promote/dismiss agentic skill/rule proposals from the webapp. id is validated to a strict
# slug so nothing but a real proposal file name can reach the subprocess.
PROPOSE = os.path.join(os.path.dirname(TOOLS_DIR), "agentic", "propose.py")
PROPOSAL_ID = re.compile(r"^(skill|rule)-[a-z0-9][a-z0-9-]*$")

_lock = threading.Lock()


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def is_enabled(name):
    """Default-enabled unless explicitly disabled in state."""
    return load_state().get(name, {}).get("enabled", True)


def set_enabled(name, enabled):
    with _lock:
        state = load_state()
        entry = state.get(name, {})
        entry["enabled"] = bool(enabled)
        state[name] = entry
        save_state(state)


def mark_run(name):
    with _lock:
        state = load_state()
        entry = state.get(name, {})
        entry["last_run"] = datetime.now(timezone.utc).isoformat()
        state[name] = entry
        save_state(state)


def run_agent(name):
    """Fire-and-forget; child inherits our environment."""
    subprocess.Popen([sys.executable, AGENTS[name]],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mark_run(name)


def wire_tool(tool):
    """Run probe.py --wire <tool> synchronously (creates CLAUDE.md + .claude/skills, etc.).
    Returns (returncode, combined_output)."""
    try:
        out = subprocess.run([sys.executable, PROBE, "--wire", tool],
                             capture_output=True, text=True, timeout=30)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as e:
        return 1, str(e)


def run_propose(action, pid):
    """promote/dismiss a proposal via propose.py. Returns (returncode, combined_output)."""
    if action not in ("promote", "dismiss") or not PROPOSAL_ID.match(pid):
        return 1, f"invalid proposal action/id: {action} {pid}"
    try:
        out = subprocess.run([sys.executable, PROPOSE, action, pid],
                             capture_output=True, text=True, timeout=30)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as e:
        return 1, str(e)


def full_state():
    state = load_state()
    return {"agents": {name: {"enabled": state.get(name, {}).get("enabled", True),
                              "last_run": state.get(name, {}).get("last_run")}
                       for name in AGENTS}}


class Handler(BaseHTTPRequestHandler):
    server_version = "hl-agent-dispatcher/1.0"

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/state":
            return self._send(200, full_state())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        parts = [p for p in self.path.split("/") if p]
        # /agents/<name>/<action>
        if len(parts) == 3 and parts[0] == "agents":
            name, action = parts[1], parts[2]
            if name not in AGENTS:
                return self._send(404, {"error": f"unknown agent: {name}"})
            if action == "enabled":
                set_enabled(name, self._body().get("enabled", True))
                return self._send(200, {"agent": name, "enabled": is_enabled(name)})
            if action == "run":
                try:
                    run_agent(name)
                    return self._send(202, {"agent": name, "status": "queued"})
                except Exception as e:
                    return self._send(500, {"error": str(e)})
        # /agentic/wire/<tool>  -> materialize that tool's workspace wiring
        if len(parts) == 3 and parts[0] == "agentic" and parts[1] == "wire":
            tool = parts[2]
            if tool not in WIREABLE:
                return self._send(404, {"error": f"not wireable: {tool}"})
            code, output = wire_tool(tool)
            return self._send(200 if code == 0 else 500,
                              {"tool": tool, "ok": code == 0, "output": output})
        # /agentic/<promote|dismiss>/<id>  -> act on a skill/rule proposal
        if len(parts) == 3 and parts[0] == "agentic" and parts[1] in ("promote", "dismiss"):
            code, output = run_propose(parts[1], parts[2])
            return self._send(200 if code == 0 else 400,
                              {"action": parts[1], "id": parts[2], "ok": code == 0, "output": output})
        self._send(404, {"error": "not found"})


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--is-enabled":
        sys.exit(0 if is_enabled(sys.argv[2]) else 1)

    bind = os.environ.get("HL_BIND", "0.0.0.0")
    port = int(os.environ.get("HL_PORT", "9099"))
    httpd = ThreadingHTTPServer((bind, port), Handler)
    print(f"agent-dispatcher listening on {bind}:{port}; state={STATE_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
