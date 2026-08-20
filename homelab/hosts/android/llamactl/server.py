"""llama-ctl — management API for the phone's local LLM.
Exposes status/models/model-switch/runbooks(read-only)/grounded-ask over HTTP on :8081.
Stdlib-only. Trusted-LAN, no auth (matches the rest of the homelab web stack).

Runbooks are READ-ONLY here — they're fetched live over SSH from noblenumbat + opti
(see askcore.load_runbooks/_SOURCES), not stored locally. There is no local copy to
edit or delete; runbooks are edited at the source (noblenumbat) instead. This replaced
an earlier design with a local rsync'd copy + editable "authored/" subdir — removed
along with the runbook-sync service once reads went live/remote (see 07-llm-
troubleshooting.md for why: no sync lag, no local disk copy, one less service to run).
"""
import os, re, json, glob, subprocess, sys
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.expanduser("~/llamactl"))
import askcore

MODELS_DIR = os.path.expanduser("~/models")
RUN_SCRIPT = os.environ.get("PREFIX", "/data/data/com.termux/files/usr") + "/var/service/llama/run"
SAFE_MODEL = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)

def current_model():
    try:
        with open(RUN_SCRIPT) as f:
            txt = f.read()
        m = re.search(r"-m\s+\S*/models/([A-Za-z0-9._-]+\.gguf)", txt)
        return m.group(1) if m else None
    except Exception:
        return None

def list_models():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(MODELS_DIR, "*.gguf")))

def llama_health():
    try:
        import urllib.request
        with urllib.request.urlopen(askcore.LLAMA_URL + "/health", timeout=5) as r:
            return json.load(r).get("status") == "ok"
    except Exception:
        return False

def battery():
    r = sh("termux-battery-status")
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

def sv_status():
    r = sh("sv status llama 2>&1")
    return r.stdout.strip()

def switch_model(name):
    if not SAFE_MODEL.match(name):
        raise ValueError("invalid model filename")
    path = os.path.join(MODELS_DIR, name)
    if not os.path.isfile(path):
        raise ValueError("model not found: " + name)
    with open(RUN_SCRIPT) as f:
        txt = f.read()
    new_txt = re.sub(r"-m\s+\S*/models/[A-Za-z0-9._-]+\.gguf", "-m " + path, txt)
    with open(RUN_SCRIPT, "w") as f:
        f.write(new_txt)
    # force-restart: TERM, then KILL after 8s. Plain restart waits for the
    # server to finish its in-flight task first — a draining prefill blocked a
    # swap for 10+ minutes (2026-08-20). Nothing durable lives in the server.
    sh("sv -w 8 force-restart llama")
    # Re-warm in the background: llama-warmup waits for the NEW model to be the
    # one serving, restores its saved slot state if present (fast swap), then
    # prefills the diff and re-saves. Without this every switch left a cold
    # cache and asks timed out for minutes (bit us 2026-08-20).
    subprocess.Popen(["llama-warmup"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True

class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/status":
            self._json(200, {
                "llama_healthy": llama_health(),
                "current_model": current_model(),
                "sv_status": sv_status(),
                "battery": battery(),
            })
        elif path == "/models":
            self._json(200, {"models": list_models(), "current": current_model()})
        elif path == "/v1/models":
            # OpenAI-compatible listing for chat UIs (Open WebUI on rpi).
            cur = current_model() or "unknown"
            self._json(200, {"object": "list", "data": [
                {"id": "homelab-grounded", "object": "model", "owned_by": "llamactl",
                 "name": "Homelab (runbook-grounded, %s)" % cur},
                {"id": "raw", "object": "model", "owned_by": "llamactl",
                 "name": "Raw (%s)" % cur},
            ]})
        elif path == "/runbooks":
            self._json(200, {"runbooks": askcore.fetch_all()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/model":
            try:
                switch_model(body.get("name", ""))
                self._json(200, {"ok": True, "current_model": current_model()})
            except Exception as e:
                self._json(400, {"error": str(e)})
        elif path == "/ask":
            q = body.get("question", "")
            if not q:
                return self._json(400, {"error": "missing question"})
            try:
                answer = askcore.ask(q, timeout=170)
                self._json(200, {"answer": answer})
            except Exception as e:
                self._json(502, {"error": "llama-server unreachable: %s" % e})
        elif path == "/v1/chat/completions":
            self._chat_completions(body)
        else:
            self._json(404, {"error": "not found"})

    # OpenAI-compatible chat endpoint so real chat UIs (Open WebUI on rpi) can
    # talk to the phone. model "homelab-grounded" injects the live runbook
    # system prompt (same grounding as /ask); "raw" (or anything else) passes
    # through untouched. Streams SSE line-by-line when the client asks — no
    # Content-Length, close-delimited body (we speak HTTP/1.0), tokens appear
    # live in the UI. A client that disconnects mid-stream does NOT cancel the
    # server-side task (known llama-server behavior, see 07 runbook).
    def _chat_completions(self, body):
        grounded = body.get("model", "homelab-grounded") != "raw"
        messages = list(body.get("messages") or [])
        if grounded:
            client_system = "\n".join(
                m.get("content", "") for m in messages if m.get("role") == "system")
            messages = [m for m in messages if m.get("role") != "system"]
            system = askcore.build_system_prompt()
            if client_system.strip():
                system += "\n\n===== EXTRA CLIENT INSTRUCTIONS =====\n" + client_system
            messages = [{"role": "system", "content": system}] + messages
        payload = dict(body)
        payload["messages"] = messages
        payload.pop("model", None)
        payload.setdefault("temperature", 0.2)
        # latency guard: at phone decode speeds an uncapped answer runs for
        # many minutes; UIs that want more can ask for it explicitly
        payload.setdefault("max_tokens", 400)
        bias = askcore._tool_token_bias()
        if bias:
            payload["logit_bias"] = bias
        req = urllib.request.Request(
            askcore.LLAMA_URL + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            upstream = urllib.request.urlopen(req, timeout=1800)
        except urllib.error.HTTPError as e:
            return self._json(e.code, {"error": e.read().decode(errors="replace")[:500]})
        except Exception as e:
            return self._json(502, {"error": "llama-server unreachable: %s" % e})
        try:
            if not payload.get("stream"):
                data = upstream.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                line = upstream.readline()
                if not line:
                    break
                self.wfile.write(line)
                if not line.strip():
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client gave up; upstream keeps decoding server-side
        finally:
            upstream.close()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    port = int(os.environ.get("LLAMA_CTL_PORT", "8081"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("llama-ctl listening on :%d" % port)
    srv.serve_forever()
