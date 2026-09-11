"""Dummy provider adapter for bridge acceptance tests. Reads the context packet from stdin and
behaves per <state_root>/dummy_behavior.json (keyed by task id, then by role), e.g.

  {"t1": {"implement": {"emit": "review_ready", "files": ["work.txt"]},
          "review":    {"emit": "review_result", "verdict": "approved"}}}

Behaviour keys: emit (kind), verdict, files (paths to write + list in the manifest, relative to cwd),
sleep (seconds), exit_code, stderr (text printed before exiting), write_outside (absolute path to
touch), no_handoff (true = finish without an envelope), session_id (echoed as JSON for extraction).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    packet_text = sys.stdin.read()
    root = Path(os.environ["BRIDGE_STATE_ROOT"])
    task_id = os.environ["BRIDGE_TASK_ID"]
    role = os.environ["BRIDGE_ROLE"]
    agent = os.environ["BRIDGE_AGENT"]
    script = os.environ["BRIDGE_SCRIPT"]
    beh_all = json.loads((root / "dummy_behavior.json").read_text(encoding="utf-8")) if (root / "dummy_behavior.json").exists() else {}
    beh = beh_all.get(task_id, {}).get(role, {})
    print(json.dumps({"session_id": beh.get("session_id", f"dummy-{task_id}-{role}")}))
    print("packet bytes:", len(packet_text))
    if beh.get("sleep"):
        time.sleep(float(beh["sleep"]))
    if beh.get("write_outside"):
        Path(beh["write_outside"]).parent.mkdir(parents=True, exist_ok=True)
        Path(beh["write_outside"]).write_text("outside\n", encoding="utf-8")
    for f in beh.get("files", []):
        p = Path(f)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{agent} {role} {time.time()}\n", encoding="utf-8")
    if beh.get("stderr"):
        print(beh["stderr"], file=sys.stderr)
    if beh.get("exit_code"):
        return int(beh["exit_code"])
    if beh.get("no_handoff"):
        return 0
    kind = beh.get("emit", "review_ready" if role in ("implement", "fix") else "review_result")
    if kind == "changes_ready" or (role == "fix" and kind == "review_ready"):
        kind = "changes_ready"
    cmd = [sys.executable, script, "--state-root", str(root), "send", "--task", task_id, "--kind", kind, "--summary", f"dummy {agent} {role}: {beh.get('summary', 'ok')}", "--sender", agent]
    if kind in ("review_ready", "changes_ready"):
        attempt = json.loads(packet_text.split("CONTEXT PACKET:\n```json\n")[1].split("\n```")[0])["task"]["attempt"]
        mf = subprocess.run([sys.executable, script, "--state-root", str(root), "manifest", "--task", task_id, "--attempt", str(attempt), *beh.get("files", [])], capture_output=True, text=True, check=True).stdout.strip()
        cmd += ["--manifest", mf]
    if kind == "review_result":
        findings = root / "artifacts" / task_id / f"findings-{role}-{int(time.time())}.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text("# findings\n- severity: low\n", encoding="utf-8")
        cmd += ["--verdict", beh.get("verdict", "approved"), "--findings", str(findings)]
    env = dict(os.environ)
    subprocess.run(cmd, check=True, env=env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
