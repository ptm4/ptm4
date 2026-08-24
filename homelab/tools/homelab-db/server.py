#!/usr/bin/env python3
"""
server.py — read-only HTTP + MCP front door for homelab.db, on opti :9100.

Two consumers, one daemon, deliberately separated by path:

    GET  /api/...   plain JSON for the webapp's widgets and Data page
    POST /mcp       Model Context Protocol, for Claude Code sessions

They share `mcp_tools` implementations but not their envelopes. MCP has shipped a
breaking revision about every six months; the browser must never care.

**MCP protocol version is pinned to 2025-06-18.** The 2026-07-28 revision removed the
initialize handshake and protocol-level sessions and added required per-request headers —
a much larger surface for no gain on a tools-only LAN server. Current Claude Code still
runs the initialize handshake, and the deprecation policy guarantees a 12-month runway,
so this pins the older revision and logs whatever the client negotiated as a drift canary.

What is implemented (and it is the whole of the spec that a tools-only server needs):
    initialize · notifications/initialized (202) · tools/list · tools/call · ping
Responses are `application/json` — a server may answer a POSTed request with plain JSON
rather than SSE, and never minting an Mcp-Session-Id makes this legitimately stateless.
GET /mcp returns 405, which the spec explicitly sanctions.

Security posture (LAN-internal, but the spec's MUSTs are MUSTs):
  - **Bearer token** on every endpoint, constant-time compared. Set HL_DB_TOKEN.
  - **Origin validation** — a hard MUST in every MCP revision. A browser that a LAN user
    visits can otherwise be used to reach this daemon (DNS rebinding); a present-and-
    unrecognised Origin gets 403. Non-browser clients send none and pass.
  - **Host allowlist** — the other half of the rebinding defence.
  - The database is opened read-only (see mcp_tools); the only thing this process writes
    is an audit row per query, through a separate connection with a fixed statement.

Env: HL_DB_BIND (0.0.0.0), HL_DB_PORT (9100), HL_DB_TOKEN (required unless
     HL_DB_ALLOW_ANONYMOUS=1), HL_DB_PATH, HL_DB_ALLOWED_HOSTS (comma-separated).
"""

import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import mcp_tools  # noqa: E402

TOKEN = os.environ.get("HL_DB_TOKEN", "")
ALLOW_ANONYMOUS = os.environ.get("HL_DB_ALLOW_ANONYMOUS") == "1"

DEFAULT_ALLOWED_HOSTS = {
    "192.168.1.11:9100", "opti:9100", "opti.lan:9100",
    "127.0.0.1:9100", "localhost:9100",
}
ALLOWED_HOSTS = {
    h.strip() for h in os.environ.get("HL_DB_ALLOWED_HOSTS", "").split(",") if h.strip()
} or DEFAULT_ALLOWED_HOSTS

# Revisions this server will answer to. A client asking for something newer is answered
# with the pinned version, which the spec allows and every current client accepts.
KNOWN_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"}

_audit_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(client, tool, detail, rows, ms, ok, error=None):
    """Append-only trail. Best-effort: a failed audit must never fail a query.

    This is the one thing the server writes, and it does so on a separate connection with
    a fixed INSERT — the connection that runs caller-supplied SQL stays read-only.
    """
    line = (f"[hldb] {tool} client={client} rows={rows} ms={ms} ok={ok}"
            + (f" error={error}" if error else ""))
    print(line, flush=True)
    try:
        with _audit_lock:
            conn = db.connect_rw(create=False)
            try:
                with db.writing(conn):
                    conn.execute(
                        """INSERT INTO query_audit (at, client, tool, detail, rows_returned, ms, ok, error)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (now_iso(), client, tool, detail, rows, ms, 1 if ok else 0, error),
                    )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[hldb] audit write failed: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-db/1.0"
    protocol_version = "HTTP/1.1"

    # ── plumbing ────────────────────────────────────────────────────────────────
    def log_message(self, *args):
        pass  # the audit trail is the log

    def _send(self, code, payload, extra_headers=None):
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _client(self):
        return self.headers.get("X-Client") or self.client_address[0]

    # ── gates ───────────────────────────────────────────────────────────────────
    def _origin_ok(self):
        """DNS-rebinding defence. Absent Origin (curl, Claude Code) passes; a browser
        Origin we do not recognise does not."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).netloc
        return host in ALLOWED_HOSTS or host.split(":")[0] in {h.split(":")[0] for h in ALLOWED_HOSTS}

    def _host_ok(self):
        host = self.headers.get("Host")
        if not host:
            return True
        return host in ALLOWED_HOSTS or host.split(":")[0] in {h.split(":")[0] for h in ALLOWED_HOSTS}

    def _authed(self):
        if ALLOW_ANONYMOUS or not TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[len("Bearer "):].strip(), TOKEN)

    def _gate(self):
        """Returns True if the request may proceed; sends the rejection itself if not."""
        if not self._host_ok():
            self._send(403, {"error": "host not allowed"})
            return False
        if not self._origin_ok():
            self._send(403, {"error": "origin not allowed"})
            return False
        if not self._authed():
            self._send(401, {"error": "unauthorized"},
                       {"WWW-Authenticate": 'Bearer realm="homelab-db"'})
            return False
        return True

    # ── routing ─────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            # No server-initiated stream; the spec sanctions answering GET with 405.
            return self._send(405, {"error": "this MCP server is POST-only (stateless)"})
        if parsed.path == "/healthz":
            return self._send(200, {"ok": True, "service": "homelab-db", "at": now_iso()})
        if not self._gate():
            return
        if not parsed.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        return self._handle_api(parsed)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._gate():
            return
        if parsed.path == "/mcp":
            return self._handle_mcp()
        if parsed.path == "/api/query":
            return self._handle_query()
        return self._send(404, {"error": "not found"})

    def _handle_query(self):
        """The webapp's SQL console. Same function, same guardrails, same audit row as
        the hl_query MCP tool — the browser is just a third client of it."""
        payload = self._body()
        if not isinstance(payload, dict):
            return self._send(400, {"error": "body must be JSON: {sql, params?}"})
        started = time.time()
        conn = db.connect_ro()
        try:
            result, is_error = mcp_tools.call_tool(conn, "hl_query", payload)
        finally:
            conn.close()
        elapsed = round((time.time() - started) * 1000, 1)
        audit(self._client(), "hl_query", f"console: {str(payload.get('sql'))[:400]}",
              _rows_of(result), elapsed, not is_error,
              result.get("error") if is_error else None)
        return self._send(400 if is_error else 200, result)

    # ── JSON API (the webapp's half) ────────────────────────────────────────────
    API_ROUTES = {
        "/api/status": ("hl_status", lambda q: {}),
        "/api/dataplane": ("hl_dataplane", lambda q: {}),
        "/api/schema": ("hl_schema", lambda q: {}),
        "/api/changes": ("hl_changes", lambda q: {"days": _int(q, "days"), "host": _one(q, "host")}),
        "/api/metrics": ("hl_metrics", lambda q: {"metric": _one(q, "metric"),
                                                  "host": _one(q, "host"), "days": _int(q, "days")}),
        "/api/search": ("hl_search_docs", lambda q: {"query": _one(q, "q") or _one(q, "query"),
                                                     "k": _int(q, "k")}),
    }

    def _handle_api(self, parsed):
        query = parse_qs(parsed.query)
        route = self.API_ROUTES.get(parsed.path)
        arguments = None

        if route is None and parsed.path.startswith("/api/host/"):
            route = ("hl_host", None)
            arguments = {"host": parsed.path[len("/api/host/"):]}
        if route is None:
            return self._send(404, {"error": "not found",
                                    "routes": sorted(self.API_ROUTES) + ["/api/host/<host>"]})

        tool, builder = route
        if arguments is None:
            arguments = {k: v for k, v in builder(query).items() if v is not None}

        started = time.time()
        conn = db.connect_ro()
        try:
            result, is_error = mcp_tools.call_tool(conn, tool, arguments)
        finally:
            conn.close()
        elapsed = round((time.time() - started) * 1000, 1)
        audit(self._client(), tool, parsed.path, _rows_of(result), elapsed,
              not is_error, result.get("error") if is_error else None)
        return self._send(400 if is_error else 200, result)

    # ── MCP (the agent's half) ──────────────────────────────────────────────────
    def _handle_mcp(self):
        payload = self._body()
        if payload is None:
            return self._send(400, _rpc_error(None, -32700, "parse error"))
        if isinstance(payload, list):
            # Batching was removed in 2025-06-18; say so rather than half-supporting it.
            return self._send(400, _rpc_error(None, -32600,
                                              "JSON-RPC batching is not supported"))
        if not isinstance(payload, dict):
            return self._send(400, _rpc_error(None, -32600, "invalid request"))

        method = payload.get("method")
        request_id = payload.get("id")

        # Notifications and responses carry no id and get an empty 202.
        if request_id is None:
            if method == "notifications/initialized":
                print("[hldb] mcp client initialized", flush=True)
            return self._send_empty(202)

        if method == "initialize":
            return self._send(200, _rpc_ok(request_id, self._initialize(payload.get("params") or {})))
        if method == "ping":
            return self._send(200, _rpc_ok(request_id, {}))
        if method == "tools/list":
            return self._send(200, _rpc_ok(request_id, {"tools": mcp_tools.tool_descriptors()}))
        if method == "tools/call":
            return self._send(200, _rpc_ok(request_id, self._tools_call(payload.get("params") or {})))

        return self._send(200, _rpc_error(request_id, -32601, f"method not found: {method}"))

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        client = (params.get("clientInfo") or {}).get("name", "unknown")
        version = (params.get("clientInfo") or {}).get("version", "?")
        # The canary: when a client stops speaking the pinned revision, this line is how
        # we find out — not a mysteriously empty tool list.
        print(f"[hldb] mcp initialize client={client}/{version} requested={requested} "
              f"serving={mcp_tools.PROTOCOL_VERSION}"
              + ("" if requested in KNOWN_PROTOCOL_VERSIONS else "  <-- UNKNOWN REVISION"),
              flush=True)
        return {
            "protocolVersion": mcp_tools.PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": mcp_tools.SERVER_INFO,
            "instructions": (
                "Read-only access to homelab.db — the homelab's own index of itself: "
                "collector history back to June 2026, host inventory, container change "
                "history, and full-text search over every runbook and rule. Prefer "
                "hl_status for 'how is the homelab', hl_search_docs before probing a host "
                "(most answers are already written down), and hl_query with hl_schema for "
                "anything the shaped tools do not cover."
            ),
        }

    def _tools_call(self, params):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        started = time.time()
        conn = db.connect_ro()
        try:
            result, is_error = mcp_tools.call_tool(conn, name, arguments)
        finally:
            conn.close()
        elapsed = round((time.time() - started) * 1000, 1)

        detail = json.dumps(arguments, default=str)[:500]
        audit(self._client(), name, detail, _rows_of(result), elapsed, not is_error,
              result.get("error") if is_error else None)

        text = result.get("error") if is_error else json.dumps(result, indent=1, default=str)
        # Structured output plus the serialized JSON text block: the spec's backwards-
        # compatible form, so clients that ignore structuredContent still see the data.
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": result,
            "isError": is_error,
        }


def _rpc_ok(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _rows_of(result):
    for key in ("row_count", "hit_count", "event_count"):
        if isinstance(result, dict) and key in result:
            return result[key]
    return None


def _one(query, key):
    values = query.get(key)
    return values[0] if values else None


def _int(query, key):
    value = _one(query, key)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def main():
    if not TOKEN and not ALLOW_ANONYMOUS:
        print("[hldb] refusing to start: set HL_DB_TOKEN (or HL_DB_ALLOW_ANONYMOUS=1 "
              "for a deliberately open instance)", file=sys.stderr)
        return 2

    try:
        conn = db.connect_ro()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[hldb] cannot open {db.db_path()}: {exc}", file=sys.stderr)
        return 1

    bind = os.environ.get("HL_DB_BIND", "0.0.0.0")
    port = int(os.environ.get("HL_DB_PORT", "9100"))
    httpd = ThreadingHTTPServer((bind, port), Handler)
    print(f"[hldb] listening on {bind}:{port} — db={db.db_path()} schema=v{version} "
          f"runs={runs} auth={'token' if TOKEN else 'ANONYMOUS'} "
          f"mcp={mcp_tools.PROTOCOL_VERSION} tools={len(mcp_tools.TOOLS)}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
