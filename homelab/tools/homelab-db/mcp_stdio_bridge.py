#!/usr/bin/env python3
"""
mcp_stdio_bridge.py — stdio ⇄ streamable-HTTP bridge for the homelab MCP server.

Claude Code speaks HTTP MCP natively (see the repo's .mcp.json), but stdio-only clients
— Claude Desktop's local-server config foremost — can only launch a subprocess and talk
newline-delimited JSON-RPC over its pipes. This is that subprocess: ~80 lines of stdlib
that forward each message to homelab-db on opti (:9100) with the bearer token and write
the response back. The usual shim for this is `npx mcp-remote`, but tux deliberately has
no node, and a stdlib bridge matches the rest of homelab/tools/.

The server is stateless (no Mcp-Session-Id, plain application/json responses, tools
only), which is what makes a bridge this small correct: every request maps to exactly
one POST, notifications get a 202 and produce no output, and there are no
server-initiated messages to stream back.

Wire-up (Claude Desktop on tux) — installed copy, so a hung CIFS mount of the repo can
never stall Desktop's MCP startup:

    cp mcp_stdio_bridge.py ~/.local/bin/hl-mcp-bridge.py
    # claude_desktop_config.json:
    #   "mcpServers": {"homelab": {"command": "python3",
    #     "args": ["/home/ptm/.local/bin/hl-mcp-bridge.py"],
    #     "env": {"HL_DB_TOKEN": "<token from opti /etc/hl-agents.env>"}}}

Env: HL_DB_MCP_URL (default http://192.168.1.11:9100/mcp), HL_DB_TOKEN.
"""

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("HL_DB_MCP_URL", "http://192.168.1.11:9100/mcp")
TOKEN = os.environ.get("HL_DB_TOKEN", "")
TIMEOUT = 60  # above the server's own 15s query budget, below anything that feels hung


def log(msg):
    # stderr is the right channel: Desktop collects it in its MCP logs, and stdout is
    # strictly the JSON-RPC stream — one stray print there corrupts the session.
    print(f"[hl-mcp-bridge] {msg}", file=sys.stderr, flush=True)


def forward(raw):
    """POST one client message; return the response body (b'' for 202/notifications)."""
    request = urllib.request.Request(
        URL, data=raw, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if TOKEN:
        request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        return resp.read()


def error_response(msg_id, code, message):
    return json.dumps({"jsonrpc": "2.0", "id": msg_id,
                       "error": {"code": code, "message": message}})


def main():
    if not TOKEN:
        log("warning: HL_DB_TOKEN is not set — every call will 401")
    log(f"bridging stdio -> {URL}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log("dropped an unparseable line from the client")
            continue
        msg_id = message.get("id") if isinstance(message, dict) else None

        try:
            body = forward(line.encode("utf-8"))
        except urllib.error.HTTPError as exc:
            if msg_id is None:
                continue  # a failed notification has no one to answer
            detail = ("unauthorized — check HL_DB_TOKEN in the Desktop config"
                      if exc.code == 401 else f"homelab-db answered HTTP {exc.code}")
            sys.stdout.write(error_response(msg_id, -32000, detail) + "\n")
            sys.stdout.flush()
            continue
        except (urllib.error.URLError, OSError) as exc:
            if msg_id is None:
                continue
            sys.stdout.write(error_response(
                msg_id, -32000,
                f"homelab-db unreachable ({exc}) — opti down or homelab-db.service stopped",
            ) + "\n")
            sys.stdout.flush()
            continue

        if body.strip():  # 202-with-no-body for notifications: nothing to write
            sys.stdout.write(body.decode("utf-8").strip() + "\n")
            sys.stdout.flush()

    log("stdin closed, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
