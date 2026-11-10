"""Tests for journald-hunter.py fleet mode (rpi + noblenumbat read from opti over SSH).

    python -m unittest discover -s homelab/tools/security -v

No host is contacted and no journal is read: the per-host reader is injected.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("journald_hunter_fleet", os.path.join(HERE, "journald-hunter.py"))
jh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jh)

NOW = 1_800_000_000.0
DISK = "blk_update_request: I/O error, dev sda, sector 123456 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 0"


def reader_from(table):
    """table: name -> (lines, ok, access, detail). Records the `since` each host got."""
    seen = {}

    def reader(name, since, local):
        seen[name] = (since, local)
        return table[name]
    return reader, seen


def alert_key_stem(message):
    # The part ingest keys alerts on: text before the first " | ", digits collapsed.
    return re.sub(r"\d+", "#", message.split(" | ", 1)[0])


class PiRules(unittest.TestCase):
    def rule(self, line):
        r = jh.classify(line)
        return None if r is None else (r[0], r[1], r[3])

    def test_undervoltage_is_a_power_warn(self):
        for line in ("hwmon hwmon1: Undervoltage detected!", "Under-voltage detected! (0x00050005)"):
            with self.subTest(line=line):
                self.assertEqual(self.rule(line), ("power", "warn", "Undervoltage"))

    def test_usb_and_uas_resets_are_storage_warns(self):
        for line in ("usb 2-1: reset SuperSpeed USB device number 2 using xhci_hcd",
                     "sd 0:0:0:0: [sda] tag#2 uas_eh_abort_handler 0 uas-tag 3 inflight: CMD OUT",
                     "scsi host0: uas_eh_device_reset_handler start"):
            with self.subTest(line=line):
                self.assertEqual(self.rule(line), ("storage", "warn", "USB device reset"))

    def test_sd_card_errors_are_critical(self):
        for line in ("mmc0: Timeout waiting for hardware interrupt.",
                     "mmcblk0: error -110 transferring data, sector 2048, nr 8, cmd response 0x900"):
            with self.subTest(line=line):
                self.assertEqual(self.rule(line), ("storage", "critical", "SD card error"))

    def test_usb_io_error_stays_a_critical_disk_error(self):
        self.assertEqual(self.rule(DISK), ("storage", "critical", "Disk / filesystem error"))

    def test_ordinary_pi_boot_lines_are_not_findings(self):
        for line in ("usb 2-1: new SuperSpeed USB device number 2 using xhci_hcd",
                     "mmc0: SDHCI controller on fe340000.mmc [fe340000.mmc] using ADMA",
                     "Voltage normalised (0x00000000)"):
            with self.subTest(line=line):
                self.assertIsNone(self.rule(line))


class Findings(unittest.TestCase):
    def test_host_prefix_and_stable_key(self):
        a = jh.build_findings(*jh.hunt([DISK] * 3)[:2], host="rpi")
        b = jh.build_findings(*jh.hunt([DISK.replace("123456", "999")] * 7)[:2], host="rpi")
        self.assertTrue(a[0]["message"].startswith("[rpi] [storage] Disk / filesystem error"))
        # different count and example, same alert key
        self.assertEqual(alert_key_stem(a[0]["message"]), alert_key_stem(b[0]["message"]))

    def test_criticals_carry_an_action(self):
        f = jh.build_findings(*jh.hunt([DISK])[:2], host="noblenumbat")[0]
        self.assertEqual(f["severity"], "critical")
        self.assertIn("smartctl", f["action"])
        # the action is in the keyed part of the message (ingest drops fields and " | ..." tails)
        self.assertIn("smartctl", f["message"].split(" | ", 1)[0])

    def test_warns_carry_no_action(self):
        f = jh.build_findings(*jh.hunt(["hwmon hwmon1: Undervoltage detected!"])[:2], host="rpi")[0]
        self.assertEqual(f["severity"], "warn")
        self.assertNotIn("action", f)

    def test_ingest_reads_the_host_column(self):
        # ingest.py: re.match(r"^\[([a-z0-9_.-]+)\]\s*", message)
        f = jh.build_findings(*jh.hunt([DISK])[:2], host="noblenumbat")[0]
        self.assertEqual(re.match(r"^\[([a-z0-9_.-]+)\]\s*", f["message"]).group(1), "noblenumbat")


class Window(unittest.TestCase):
    def test_first_run_uses_hours(self):
        self.assertEqual(jh.since_for("rpi", {}, NOW, 24), NOW - 24 * 3600)

    def test_resumes_from_last_good_read(self):
        self.assertEqual(jh.since_for("rpi", {"rpi": {"last_ok": NOW - 3600}}, NOW, 24), NOW - 3600)

    def test_catch_up_is_capped(self):
        old = {"rpi": {"last_ok": NOW - 30 * 86400}}
        self.assertEqual(jh.since_for("rpi", old, NOW, 24), NOW - jh.FLEET_MAX_DAYS * 86400)

    def test_remote_read_is_bounded_and_low_priority(self):
        cmd = jh.fleet_cmd(NOW - 3600, remote=True)
        self.assertEqual(cmd[:5], ["nice", "-n", "19", "ionice", "-c3"])
        self.assertIn(f"@{int(NOW - 3600)}", cmd)
        self.assertEqual(cmd[cmd.index("-n", 5) + 1], str(jh.FLEET_LINE_CAP))
        self.assertEqual(jh.fleet_cmd(NOW, remote=False)[0], "journalctl")


class Fleet(unittest.TestCase):
    def run_fleet(self, table, state=None):
        reader, seen = reader_from(table)
        with mock.patch.object(jh, "_local_name", return_value="opti"):
            out = jh.hunt_fleet(list(table), 24, reader=reader, state=state or {}, now=NOW)
        return out, seen

    def test_each_host_is_hunted_and_tagged(self):
        (findings, blocks, by_cat, state, total), seen = self.run_fleet({
            "opti": (["ordinary line"], True, "full", "local"),
            "rpi": ([DISK, "hwmon hwmon1: Undervoltage detected!"], True, "full", "ssh"),
            "noblenumbat": (["ordinary"] * 5, True, "full", "ssh"),
        })
        self.assertEqual([b["host"] for b in blocks], ["opti", "rpi", "noblenumbat"])
        self.assertEqual({b["host"]: b["status"] for b in blocks},
                         {"opti": "ok", "rpi": "critical", "noblenumbat": "ok"})
        self.assertTrue(all(f["message"].startswith("[rpi] ") for f in findings))
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertEqual(total, 8)
        self.assertEqual(dict(by_cat), {"storage": 1, "power": 1})
        self.assertTrue(seen["opti"][1] and not seen["rpi"][1])
        self.assertEqual(state["rpi"]["last_ok"], NOW)

    def test_unreachable_host_is_a_warn_and_keeps_its_cursor(self):
        prior = {"rpi": {"last_ok": NOW - 7200}}
        (findings, blocks, _c, state, _t), _seen = self.run_fleet(
            {"rpi": ([], False, None, "ssh failed (host down or key not authorized)")}, state=prior)
        self.assertEqual(findings[0]["severity"], "warn")
        self.assertTrue(findings[0]["message"].startswith("[rpi] [hunter] Journal not read"))
        self.assertEqual(state["rpi"]["last_ok"], NOW - 7200)
        self.assertEqual(blocks[0]["status"], "warn")

    def test_partial_remote_read_is_flagged(self):
        (findings, _b, _c, _s, _t), _seen = self.run_fleet({"rpi": (["x"], True, "partial", "ssh")})
        self.assertTrue(findings[0]["message"].startswith("[rpi] [hunter] Partial journal read"))

    def test_capped_read_is_flagged(self):
        lines = ["x"] * jh.FLEET_LINE_CAP
        (findings, _b, _c, _s, _t), _seen = self.run_fleet({"noblenumbat": (lines, True, "full", "ssh")})
        self.assertTrue(any("Journal read capped" in f["message"] for f in findings))

    def test_remote_ids_decide_access(self):
        self.assertEqual(jh.access_from_ids("1000", "ptm adm sudo docker"), "full")
        self.assertEqual(jh.access_from_ids("1000", "ptm sudo docker"), "partial")
        self.assertEqual(jh.access_from_ids("0", "root"), "full")

    def test_android_is_never_read(self):
        with mock.patch.dict(os.environ, {"HL_JOURNAL_HOSTS": "opti, rpi,android,noblenumbat"}):
            self.assertEqual(jh.fleet_names(None), ["opti", "rpi", "noblenumbat"])

    def test_no_hosts_configured_means_local_mode(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HL_JOURNAL_HOSTS", None)
            self.assertEqual(jh.fleet_names(None), [])


class FleetReport(unittest.TestCase):
    def test_report_and_state_are_written(self):
        table = {"opti": (["fine"], True, "full", "local"), "rpi": ([DISK], True, "full", "ssh")}
        reader, _seen = reader_from(table)
        real = jh.hunt_fleet
        with tempfile.TemporaryDirectory() as d:
            report_path = os.path.join(d, "journal-hunt-latest.json")
            state_path = os.path.join(d, "journal-hunt-state.json")
            with mock.patch.object(jh, "REPORTS_DIR", d), mock.patch.object(jh, "REPORT_PATH", report_path), \
                 mock.patch.object(jh, "STATE_PATH", state_path), \
                 mock.patch.object(jh, "_local_name", return_value="opti"), \
                 mock.patch.object(jh, "hunt_fleet", lambda names, hours, state=None: real(
                     names, hours, reader=reader, state=state, now=NOW)), \
                 mock.patch.object(sys, "argv", ["journald-hunter.py", "--hosts", "opti,rpi"]), \
                 mock.patch("builtins.print"):
                jh.main()
            with open(report_path) as f:
                rep = json.load(f)
            with open(state_path) as f:
                st = json.load(f)
        self.assertEqual(rep["status"], "critical")
        self.assertEqual([h["host"] for h in rep["hosts"]], ["opti", "rpi"])
        self.assertEqual(rep["hosts"][1]["metrics"]["critical"], 1)
        self.assertEqual(st["rpi"]["last_ok"], NOW)


if __name__ == "__main__":
    unittest.main()
