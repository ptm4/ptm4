"""Shared runbook-grounded Q&A logic, used by both the `ask` CLI and llama-ctl server.

Runbooks are read LIVE over SSH from opti on every call — no local sync, no local copy,
nothing on disk here. Both sources live on opti (the ptm4 repo checkout is there — see
project memory 2026-07-22: the noblenumbat clone was deleted, opti is the code+Claude
target again) and are fetched in a SINGLE SSH round trip, each script printing one line
of JSON ([{name, content}]):
  - ~/bin/dump-runbooks.sh -- hand-authored runbooks (source of truth,
    homelab/agentic/runbooks/ in the ptm4 repo).
  - ~/bin/dump-docs.sh -- auto-generated homelab docs (from docs-generator.py),
    homelab agent-logs/generated-docs/.
Uses the phone's existing unrestricted key to opti (a prior, separate decision — see
project memory). Replaced the old rsync-to-local-disk + runbook-sync polling service
design: that added a disk copy, a ~120s staleness window, and a separate service to keep
running. A live SSH fetch is simpler (no sync lag, no local storage, no service to
babysit) and cheap (~0.3-0.7s round trip, negligible next to multi-second LLM inference).
"""
import os, re, json, subprocess, urllib.request

LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080")

_REMOTE_CMD = ["ssh", "opti", "~/bin/dump-runbooks.sh; ~/bin/dump-docs.sh"]
_SOURCE_LABELS = ["authored", "generated"]  # one per line of output, in order

def fetch_all():
    """Structured fetch: [{name, content, source, error}], source-labeled, for the
    webapp's runbook list. On total failure (opti unreachable), returns one entry with
    error set rather than silently returning nothing."""
    try:
        out = subprocess.run(_REMOTE_CMD, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return [{"name": "(opti unreachable)", "content": "", "source": "opti", "error": str(e)}]
    if out.returncode != 0:
        return [{"name": "(opti unreachable)", "content": "", "source": "opti",
                 "error": out.stderr.strip() or "non-zero exit"}]
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    result = []
    for label, line in zip(_SOURCE_LABELS, lines):
        try:
            for f in json.loads(line):
                result.append({"name": f["name"], "content": f["content"], "source": label, "error": None})
        except Exception as e:
            result.append({"name": "(%s unavailable)" % label, "content": "", "source": label, "error": str(e)})
    return result

def load_runbooks():
    parts = []
    for f in fetch_all():
        if f["error"]:
            parts.append("### SOURCE UNAVAILABLE: %s (%s)" % (f["source"], f["error"]))
        else:
            parts.append("### FILE: %s\n%s" % (f["name"], f["content"]))
    return "\n\n".join(parts)

def build_system_prompt(runbooks_text=None):
    books = runbooks_text if runbooks_text is not None else load_runbooks()
    # Structure: runbooks FIRST, instructions LAST. Two reasons (2026-08-20):
    # 1. Cache economics — the llama-server prefix cache invalidates from the first
    #    changed token. Instructions-first meant every instruction tweak recolded the
    #    entire ~10k-token prefill (~10 min); instructions-last makes it seconds.
    # 2. Instruction adherence is better when the rules sit closest to the question.
    # The no-tools clause is load-bearing (agent-tuned LFM2.5 hallucinates read()
    # calls at the FILE headers) and belt-and-braces with the logit_bias ban below.
    return (
        "You are the homelab assistant for Peter's home lab. The complete runbooks "
        "follow; your answering instructions come after them.\n\n"
        "===== RUNBOOKS =====\n" + books + "\n\n===== INSTRUCTIONS =====\n"
        "Answer the user's question using ONLY the runbooks above. State the facts "
        "immediately and directly — no preamble, no narrating your search (never write "
        "\"I need to look at...\" or \"From the runbooks...\"), no meta-commentary. "
        "2-4 short sentences or a brief list; this runs on a phone CPU, do not write "
        "essays. You have NO tools, NO functions, and NO file access — every runbook "
        "is already above; never emit tool-call syntax; plain prose only. If a "
        "question is broad, give a short summary and name which doc has the detail. "
        "If the answer is not in the runbooks, say exactly: \"That's not in the "
        "runbooks.\" Do not invent hosts, commands, or file paths."
    )

# Agent-tuned models (LFM2.5) emit raw tool-call tokens at the ### FILE: headers
# even when the system prompt forbids it — the prompt clause alone did NOT stop it
# (tested 2026-08-20). Banning the tokens via logit_bias is deterministic and does
# not touch the prompt (so the warm prefix cache survives). Token ids are resolved
# per-request from the live model via /tokenize: a single-token parse means the
# model really has that special token; multi-token means it doesn't (e.g. qwen),
# and we must NOT ban — the ids would hit arbitrary unrelated vocab entries.
_TOOL_TOKEN_STRINGS = ("<|tool_call_start|>", "<|tool_call_end|>")

def _tool_token_bias():
    bias = {}
    for s in _TOOL_TOKEN_STRINGS:
        try:
            req = urllib.request.Request(
                LLAMA_URL + "/tokenize",
                data=json.dumps({"content": s, "add_special": False,
                                 "parse_special": True}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                toks = json.load(r).get("tokens", [])
            if len(toks) == 1:
                bias[str(toks[0])] = -100
        except Exception:
            pass  # tokenizer endpoint unavailable — degrade to prompt-only defense
    return bias

# max_tokens is a hard latency bound, not a style preference: at this context size
# (~8k tokens with the generated docs included), CPU generation runs ~1.5-2.5 tok/s
# even with a warm prompt cache (attention cost scales with context length). 200
# tokens caps worst-case generation at ~2 min, comfortably inside the timeout chain
# (llama-ctl 170s < webapp fetch 180s < nginx 240s). Don't raise this without also
# raising all three, in that order, or a long answer will 502/504 instead of finishing.
def chat(messages, temperature=0.2, max_tokens=200, timeout=180):
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    bias = _tool_token_bias()
    if bias:
        payload["logit_bias"] = bias
    req = urllib.request.Request(
        LLAMA_URL + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    content = data["choices"][0]["message"]["content"]
    # --reasoning-budget 0 leaves an empty <think></think> prefix in content on
    # some templates (LFM2.5) — cosmetic, strip it
    return re.sub(r"^\s*<think>\s*</think>\s*", "", content).strip()

def ask(question, timeout=180):
    system = build_system_prompt()
    return chat(
        [{"role": "system", "content": system}, {"role": "user", "content": question}],
        timeout=timeout,
    )
