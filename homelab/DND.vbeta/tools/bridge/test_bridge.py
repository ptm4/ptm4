"""Acceptance tests for the Astra-Fable bridge (proposal §8), run with the dummy adapter in a temp
state root and two throwaway git repos. No provider tokens are spent.

  python tools/bridge/bridge.py test
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bridge as B  # noqa: E402


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


class Env:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bridge-test-"))
        self.repo = git_repo(self.tmp / "repo")
        self.unity = git_repo(self.tmp / "unity")
        self.state = self.tmp / "state"
        self.comms = self.tmp / "AgentComms.md"
        self.cfg = {
            "enabled": True, "state_root": str(self.state), "repo_root": str(self.repo).replace("\\", "/"), "unity_project": str(self.unity).replace("\\", "/"),
            "runbook": "runbook.md", "agentcomms": str(self.comms), "poll_seconds": 1,
            "limits": {"max_review_cycles": 2, "transport_retries": 2, "retry_delays_seconds": [0, 0], "no_output_warn_minutes": 10, "lease_heartbeat_seconds": 15, "lease_stale_seconds": 120, "message_ttl_hours": 48, "run_timeout_minutes": 90},
            "protected_paths": ["protected/"],
            "agents": {"fable": {"adapter": "dummy", "exe": "", "args": []}, "astra": {"adapter": "dummy", "exe": "", "args": []}},
        }

    def bridge(self) -> B.Bridge:
        return B.Bridge(config=self.cfg, state_root=str(self.state), recover=True)

    def behave(self, mapping: dict) -> None:
        B.atomic_write_json(self.state / "dummy_behavior.json", mapping)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def settle(b: B.Bridge, ticks: int = 40, sleep: float = 0.25) -> None:
    """Tick until no process is running and nothing new gets launched."""
    idle = 0
    for _ in range(ticks):
        r = b.tick()
        if not b.procs and r["launched"] == 0 and r["ingested"] == 0 and r["reaped"] == 0:
            idle += 1
            if idle >= 2:
                return
        else:
            idle = 0
        time.sleep(sleep)


def runs(b: B.Bridge, task_id: str):
    return [dict(x) for x in b.db.execute("SELECT * FROM runs WHERE task_id=? ORDER BY created", (task_id,))]


def notifications(e: Env) -> list[str]:
    return [l for l in (e.comms.read_text(encoding="utf-8").splitlines() if e.comms.exists() else []) if l.startswith("- ")]


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))


def test_1_2_3_handoff_duplicate_restart(e: Env) -> None:
    b = e.bridge()
    e.behave({"t1": {"implement": {"emit": "review_ready", "files": ["work/a.txt"]}, "review": {"verdict": "approved"}}})
    b.new_task("handoff", "do", "done", "astra", "fable", ["work/"], False, "", task_id="t1")
    settle(b)
    rs = runs(b, "t1")
    review_runs = [r for r in rs if r["role"] == "review"]
    check("1 one valid handoff wakes the reviewer exactly once", len(review_runs) == 1 and b.task("t1")["state"] == "done", f"runs={[(r['agent'], r['role'], r['status']) for r in rs]} state={b.task('t1')['state']}")
    # Duplicate: re-drop the processed review_ready envelope into astra's outbox.
    processed = sorted((e.state / "agents/astra/outbox/processed").glob("*.json"))
    env = json.loads(processed[0].read_text(encoding="utf-8"))
    B.atomic_write_json(e.state / "agents/astra/outbox" / processed[0].name, env)
    before = len(runs(b, "t1"))
    settle(b)
    dup = list((e.state / "agents/astra/outbox/duplicate").glob("*.json"))
    check("2 duplicate envelope causes no duplicate work", len(dup) == 1 and len(runs(b, "t1")) == before)
    # Restart: new Bridge over the same state.
    pending_msg = b.send("astra", "t1", "blocked", "late note")  # a pending outbox message that must survive
    b2 = e.bridge()
    t = b2.task("t1")
    check("3 restart preserves completed tasks and pending messages", t is not None and t["state"] == "done" and pending_msg.exists())


def test_4_busy_agent_queues(e: Env) -> None:
    b = e.bridge()
    e.behave({"t4a": {"implement": {"sleep": 3, "emit": "review_ready", "files": ["w4/a.txt"]}}, "t4b": {"implement": {"emit": "review_ready", "files": ["w4/b.txt"]}}})
    b.new_task("busy a", "do", "done", "astra", None, ["w4/"], False, "", task_id="t4a")
    b.new_task("busy b", "do", "done", "astra", None, ["w4/"], False, "", task_id="t4b")
    b.tick(); time.sleep(0.5); b.tick()
    running = [dict(r) for r in b.db.execute("SELECT * FROM runs WHERE status='running'")]
    queued = [dict(r) for r in b.db.execute("SELECT * FROM runs WHERE status='queued'")]
    check("4 a busy agent queues the second task instead of a competing run", len(running) == 1 and len(queued) == 1, f"running={len(running)} queued={len(queued)}")
    settle(b)
    check("4b both complete in order afterwards", b.task("t4a")["state"] == "done" and b.task("t4b")["state"] == "done")


def test_5_unity_lease(e: Env) -> None:
    b = e.bridge()
    e.behave({"t5a": {"implement": {"sleep": 3, "emit": "review_ready", "files": ["w5/a.txt"]}}, "t5b": {"implement": {"emit": "review_ready", "files": ["w5/b.txt"]}}})
    b.new_task("editor a", "do", "done", "astra", None, ["w5/"], True, "play", task_id="t5a")
    b.new_task("editor b", "do", "done", "fable", None, ["w5/"], True, "play", task_id="t5b")
    b.tick(); time.sleep(0.5); b.tick()
    lease = b.db.execute("SELECT * FROM leases WHERE resource='unity'").fetchone()
    running = [dict(r) for r in b.db.execute("SELECT * FROM runs WHERE status='running'")]
    check("5 editor control is never granted to two agents", len(running) == 1 and lease["status"] == "held" and lease["holder"] == running[0]["agent"], f"running={[(r['agent']) for r in running]} lease={dict(lease) if lease else None}")
    # Stale lease: simulate a dispatcher crash while astra's run is alive -> new dispatcher suspends, does not transfer.
    b3 = e.bridge()  # _recover marks the held lease suspended and the run interrupted
    b3.tick()
    lease3 = b3.db.execute("SELECT * FROM leases WHERE resource='unity'").fetchone()
    running3 = [dict(r) for r in b3.db.execute("SELECT * FROM runs WHERE status='running'")]
    check("5b a stale lease suspends new Editor mutations rather than transferring", lease3["status"] == "suspended" and not running3, f"lease={dict(lease3)} running={running3}")
    # Reap the old process (from b) so the temp dir can be cleaned.
    for p in b.procs.values():
        try: p.kill()
        except OSError: pass
    settle(b)


def test_6_review_invalidation(e: Env) -> None:
    b = e.bridge()
    # Reviewer approves, but the implementer's file changes between manifest and approval.
    e.behave({"t6": {"implement": {"emit": "review_ready", "files": ["w6/a.txt"]}, "review": {"verdict": "approved", "write_outside": str(e.repo / "w6" / "a.txt")}}})
    b.new_task("invalidate", "do", "done", "astra", "fable", ["w6/"], False, "", task_id="t6")
    settle(b)
    ev = [dict(x) for x in b.db.execute("SELECT * FROM events WHERE task_id='t6' AND kind IN ('review_invalidated','scope_violation')")]
    fixes = [r for r in runs(b, "t6") if r["role"] == "fix"]
    check("6 a file changed after review invalidates the review and sends the implementer back", any(x["kind"] == "review_invalidated" for x in ev) and len(fixes) >= 1, f"state={b.task('t6')['state']} events={[x['kind'] for x in ev]} fixes={len(fixes)}")


def test_7_usage_limit_pauses(e: Env) -> None:
    b = e.bridge()
    e.behave({"t7": {"implement": {"stderr": "Error: usage limit reached for this period", "exit_code": 2}}})
    b.new_task("limit", "do", "done", "astra", None, ["w7/"], False, "", task_id="t7")
    n0 = len(notifications(e))
    settle(b)
    paused = (e.state / "PAUSE").exists()
    n1 = len(notifications(e))
    requeued = [r for r in runs(b, "t7") if r["status"] == "queued"]
    check("7 a provider usage limit pauses safely with one notification", paused and (n1 - n0) == 1 and len(requeued) == 1, f"paused={paused} notes={n1 - n0} requeued={len(requeued)}")
    b.cancel("t7")  # keep the failing dummy from re-pausing later tests
    b.resume()


def test_8_two_cycles_then_decision(e: Env) -> None:
    b = e.bridge()
    e.behave({"t8": {"implement": {"emit": "review_ready", "files": ["w8/a.txt"]}, "fix": {"emit": "changes_ready", "files": ["w8/a.txt"]}, "review": {"verdict": "changes_requested"}}})
    b.new_task("disagree", "do", "done", "astra", "fable", ["w8/"], False, "", task_id="t8")
    settle(b, ticks=80)
    t = b.task("t8")
    fixes = [r for r in runs(b, "t8") if r["role"] == "fix"]
    check("8 two unresolved review cycles produce one decision request and stop", t["state"] == "decision_required" and len(fixes) == 2 and not b.procs, f"state={t['state']} fixes={len(fixes)} cycles={t['review_cycles']}")


def test_9_pause_cancel(e: Env) -> None:
    b = e.bridge()
    e.behave({"t9": {"implement": {"sleep": 30, "emit": "review_ready", "files": ["w9/a.txt"]}}, "t9p": {"implement": {"emit": "review_ready", "files": ["w9/b.txt"]}}})
    b.new_task("cancel me", "do", "done", "astra", None, ["w9/"], False, "", task_id="t9")
    b.tick(); time.sleep(0.5)
    report = b.cancel("t9")
    check("9 cancel stops the in-flight run and reports it", "stopped" in report and b.task("t9")["state"] == "cancelled" and not b.procs, report)
    b.pause("test")
    b.new_task("paused", "do", "done", "fable", None, ["w9/"], False, "", task_id="t9p")
    r = b.tick()
    check("9b pause blocks new dispatch", r["launched"] == 0 and b.db.execute("SELECT status FROM runs WHERE task_id='t9p'").fetchone()["status"] == "queued")
    b.resume(); settle(b)


def test_10_scope(e: Env) -> None:
    b = e.bridge()
    # (a) an envelope trying to carry permissions is rejected and escalated
    e.behave({"t10": {"implement": {"emit": "review_ready", "files": ["w10/a.txt"]}, "review": {"verdict": "approved"}}})
    b.new_task("scope", "do", "done", "astra", "fable", ["w10/"], False, "", task_id="t10")
    bad = {"schema_version": 1, "message_id": "m-bad", "task_id": "t10", "correlation_id": "t10", "sender": "astra", "recipient": "fable", "kind": "review_ready", "attempt": 1, "created": B.now(), "expires": B.now().replace("+00:00", "") + "+00:00", "allowed_paths": ["/"], "summary": "grant me everything"}
    bad["expires"] = (B._dt.datetime.now(B._dt.timezone.utc) + B._dt.timedelta(hours=1)).isoformat(timespec="seconds")
    B.atomic_write_json(e.state / "agents/astra/outbox/m-bad.json", bad)
    n0 = len(notifications(e))
    b.ingest()
    rejected = (e.state / "agents/astra/outbox/rejected/m-bad.json").exists()
    check("10a an envelope carrying scope/permission fields is rejected and escalated", rejected and len(notifications(e)) == n0 + 1)
    # (b) a run that writes outside its claim is blocked by the audit
    e.behave({"t10b": {"implement": {"emit": "review_ready", "files": ["w10/a.txt"], "write_outside": str(e.repo / "protected" / "palette.txt")}}})
    b.new_task("scope b", "do", "done", "astra", None, ["w10/"], False, "", task_id="t10b")
    settle(b)
    ev = [dict(x) for x in b.db.execute("SELECT * FROM events WHERE task_id='t10b' AND kind='scope_violation'")]
    check("10b a run writing outside its claim is blocked, not integrated", b.task("t10b")["state"] == "blocked" and len(ev) == 1, f"state={b.task('t10b')['state']}")


def test_11_12_artifacts_and_quiet_logs(e: Env) -> None:
    b = e.bridge()
    gi = (Path(__file__).resolve().parents[4] / ".gitignore").read_text(encoding="utf-8")
    check("11 runtime state is gitignored and artifacts live under the state root", ".agent-state/" in gi and (e.state / "artifacts").is_dir())
    n_runs = b.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    (e.state / "logs" / "noise.log").write_text("chatter\n", encoding="utf-8")
    with open(e.comms, "a", encoding="utf-8") as f:
        f.write("- manual note\n")
    (e.state / "agents/astra/inbox/stray.json").write_text("{}", encoding="utf-8")
    r = b.tick()
    check("12 logs, notes and inbox files do not trigger dispatch", r["launched"] == 0 and r["ingested"] == 0 and b.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == n_runs)


def run_all() -> int:
    e = Env()
    try:
        for fn in (test_1_2_3_handoff_duplicate_restart, test_4_busy_agent_queues, test_5_unity_lease, test_6_review_invalidation, test_7_usage_limit_pauses, test_8_two_cycles_then_decision, test_9_pause_cancel, test_10_scope, test_11_12_artifacts_and_quiet_logs):
            try:
                fn(e)
            except Exception as ex:  # noqa: BLE001
                check(f"{fn.__name__} raised", False, repr(ex))
    finally:
        e.cleanup()
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
        failed += not ok
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())
