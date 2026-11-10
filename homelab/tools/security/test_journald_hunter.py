"""Tests for journald-hunter.py: self-matching noise stays out, real disk/kernel errors stay in.

    python -m unittest discover -s homelab/tools/security -v

The sample lines are real shapes from opti's journal (journalctl -o cat), with numbers,
devices and hosts kept but nothing secret. No journal is read and no file is written.
"""
import importlib.util
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("journald_hunter", os.path.join(HERE, "journald-hunter.py"))
jh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jh)


def rule_of(line):
    rule = jh.classify(line)
    return None if rule is None else (rule[0], rule[1], rule[3])


# Lines that produced the daily "[storage] SMART / disk-health warning" and the other
# self-matches. None of these may count under storage or kernel.
NOISE = [
    # ingest.py's own per-cycle stats line
    '[ingest] {"reports": 7, "security_reports": 2, "change_events": 0, "docs": 0, "raw": 4, '
    '"incidents": 16, "monitors": 31, "devices": "16 (0 new)", "pihole_days": 1, "media": 4, '
    '"certificates": 2, "cert_warnings": 0, "smart_flags": 2}',
    # hardware-report's sudo audit lines
    "     ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/smartctl -H -A /dev/sda",
    "     ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/smartctl -i /dev/sdc",
    "     ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/smartctl -H -A -l error /dev/sdb",
    "     ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/bin/journalctl -t smartd --no-pager --since '24 hours ago'",
    "     ptm : TTY=pts/0 ; PWD=/home/ptm ; USER=root ; COMMAND=/usr/bin/grep -i 'I/O error' /var/log/syslog",
    # smartd attribute chatter that is not a defect
    "Device: /dev/sda [SAT], SMART Usage Attribute: 194 Temperature_Celsius changed from 64 to 62",
    "Device: /dev/sdb [SAT], SMART Usage Attribute: 190 Airflow_Temperature_Cel changed from 63 to 61",
    "Device: /dev/sdb [SAT], SMART Prefailure Attribute: 1 Raw_Read_Error_Rate changed from 117 to 118",
    "Device: /dev/sdb [SAT], SMART Usage Attribute: 195 ECC_On_the_Fly_Count changed from 49 to 50",
    "Device: /dev/sda [SAT], SMART Usage Attribute: 9 Power_On_Hours changed from 98 to 97",
    # sshd debug output that used to read as a kernel BUG (Oct 1 / Oct 3 criticals)
    "fatal: ssh_packet_send_debug: send DEBUG: Broken pipe",
    # PAM session lines for cron and sudo (collectors and root cron jobs)
    "pam_unix(cron:session): session opened for user root(uid=0) by (uid=0)",
    "pam_unix(sudo:session): session opened for user root(uid=0) by (uid=1000)",
    # lowercase "oops" in ordinary output is not a kernel oops
    "notify.py: oops, retrying ntfy publish",
]

# Real disk / kernel errors: each must still be caught, with the expected category.
REAL = [
    ("storage", "ata1.00: failed command: READ FPDMA QUEUED"),
    ("storage", "ata3: SError: { UnrecovData Handshk } error"),
    ("storage", "blk_update_request: I/O error, dev sdb, sector 123456 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 0"),
    ("storage", "Buffer I/O error on dev sdb1, logical block 15, async page read"),
    ("storage", "EXT4-fs error (device sdb1): ext4_find_entry:1455: inode #2: comm ls: reading directory lblock 0"),
    ("storage", "sd 2:0:0:0: [sdb] tag#3 Sense Key : Medium Error [current] critical medium error"),
    ("storage", "Device: /dev/sdb [SAT], 8 Currently unreadable (pending) sectors"),
    ("storage", "Device: /dev/sdb [SAT], 8 Offline uncorrectable sectors"),
    ("storage", "Device: /dev/sdb [SAT], ATA error count increased from 0 to 3"),
    ("storage", "Device: /dev/sdb [SAT], Self-Test Log error count increased from 0 to 1"),
    ("storage", "Device: /dev/sdb [SAT], SMART Prefailure Attribute: 5 Reallocated_Sector_Ct changed from 100 to 99"),
    ("storage", "Device: /dev/sdb [SAT], SMART Usage Attribute: 197 Current_Pending_Sector changed from 100 to 99"),
    ("storage", "Device: /dev/sdb [SAT], FAILED SMART self-check. BACK UP DATA NOW!"),
    ("storage", "Device: /dev/sdb [SAT], Failed SMART usage Attribute: 5 Reallocated_Sector_Ct."),
    ("kernel", "BUG: unable to handle page fault for address: ffffffffc0a1b2c3"),
    ("kernel", "kernel BUG at mm/slub.c:4022!"),
    ("kernel", "mce: [Hardware Error]: Machine check events logged"),
    ("kernel", "Oops: 0000 [#1] PREEMPT SMP NOPTI"),
    ("kernel", "python3[1234]: segfault at 0 ip 00007f sp 00007ffd error 4 in libc.so.6"),
]


class Noise(unittest.TestCase):
    def test_noise_lines_do_not_count_as_storage_or_kernel(self):
        for line in NOISE:
            with self.subTest(line=line[:70]):
                r = rule_of(line)
                self.assertFalse(r is not None and r[0] in ("storage", "kernel"), f"counted as {r}")

    def test_collector_bookkeeping_is_skipped_entirely(self):
        for line in (NOISE[0], NOISE[12], NOISE[13]):
            with self.subTest(line=line[:70]):
                self.assertIsNone(rule_of(line))

    def test_hunt_over_noise_reports_no_findings(self):
        counts, _examples, worst = jh.hunt(NOISE)
        self.assertEqual(dict(counts), {})
        self.assertEqual(worst, "info")


class RealErrors(unittest.TestCase):
    def test_real_errors_are_caught(self):
        for category, line in REAL:
            with self.subTest(line=line[:70]):
                r = rule_of(line)
                self.assertIsNotNone(r, "missed")
                self.assertEqual(r[0], category)
                self.assertIn(r[1], ("warn", "critical"))

    def test_smart_self_check_failure_is_critical(self):
        r = rule_of("Device: /dev/sdb [SAT], FAILED SMART self-check. BACK UP DATA NOW!")
        self.assertEqual(r, ("storage", "critical", "SMART health failure"))

    def test_pending_sectors_are_a_warn(self):
        r = rule_of("Device: /dev/sdb [SAT], 8 Currently unreadable (pending) sectors")
        self.assertEqual(r, ("storage", "warn", "SMART / disk-health warning"))

    def test_real_errors_survive_amid_noise(self):
        lines = NOISE * 50 + ["Device: /dev/sdb [SAT], 8 Currently unreadable (pending) sectors"]
        counts, examples, worst = jh.hunt(lines)
        key = ("storage", "warn", "SMART / disk-health warning")
        self.assertEqual(dict(counts), {key: 1})
        self.assertIn("pending", examples[key])
        self.assertEqual(worst, "warn")


class Security(unittest.TestCase):
    def test_account_change_via_sudo_is_still_critical(self):
        # Peter's real 2026-09-10 change: must keep raising a critical
        r = rule_of("     ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/usermod -aG docker ptm")
        self.assertEqual(r[:2], ("security", "critical"))

    def test_ssh_and_su_root_sessions_still_count(self):
        for line in ("pam_unix(sshd:session): session opened for user root(uid=0) by (uid=0)",
                     "pam_unix(su:session): session opened for user root(uid=0) by ptm(uid=1000)"):
            with self.subTest(line=line):
                self.assertEqual(rule_of(line)[2], "Privilege escalation (su/root session)")

    def test_failed_ssh_login_still_counts(self):
        self.assertEqual(rule_of("Failed password for invalid user admin from 203.0.113.9 port 4242 ssh2")[:2],
                         ("security", "warn"))


class JournalAccess(unittest.TestCase):
    def setUp(self):
        if not hasattr(os, "geteuid"):
            self.skipTest("POSIX-only (needs geteuid/grp)")
        import grp
        self.grp = grp

    def _groups(self, names):
        gids = {"systemd-journal": 990, "adm": 4, "wheel": 10}
        def getgrnam(name):
            if name not in gids:
                raise KeyError(name)
            return mock.Mock(gr_gid=gids[name])
        return gids, getgrnam

    def test_root_is_full(self):
        with mock.patch.object(os, "geteuid", return_value=0):
            self.assertEqual(jh.journal_access(), "full")

    def test_user_without_journal_group_is_partial(self):
        gids, getgrnam = self._groups([])
        with mock.patch.object(os, "geteuid", return_value=1000), \
             mock.patch.object(os, "getgroups", return_value=[100, 27, 1000]), \
             mock.patch.object(os, "getegid", return_value=100), \
             mock.patch.object(self.grp, "getgrnam", side_effect=getgrnam):
            self.assertEqual(jh.journal_access(), "partial")

    def test_user_in_systemd_journal_is_full(self):
        gids, getgrnam = self._groups([])
        with mock.patch.object(os, "geteuid", return_value=1000), \
             mock.patch.object(os, "getgroups", return_value=[100, 990]), \
             mock.patch.object(os, "getegid", return_value=100), \
             mock.patch.object(self.grp, "getgrnam", side_effect=getgrnam):
            self.assertEqual(jh.journal_access(), "full")


class Reading(unittest.TestCase):
    def test_journal_cmd_is_prefixable(self):
        cmd = jh.journal_cmd(24)
        self.assertEqual(cmd[0], "journalctl")
        self.assertIn("24 hours ago", cmd)
        self.assertIn("cat", cmd)

    def test_journal_lines_uses_given_cmd(self):
        done = mock.Mock(returncode=0, stdout="a\nb\n")
        with mock.patch.object(jh.subprocess, "run", return_value=done) as run:
            self.assertEqual(jh.journal_lines(24, cmd=["ssh", "rpi"] + jh.journal_cmd(24)), ["a", "b"])
            self.assertEqual(run.call_args[0][0][:2], ["ssh", "rpi"])

    def test_read_lines_falls_back_to_files_when_journal_is_empty(self):
        with mock.patch.object(jh, "have_journalctl", return_value=True), \
             mock.patch.object(jh, "journal_lines", return_value=[]), \
             mock.patch.object(jh, "file_lines", return_value=["x"]):
            self.assertEqual(jh.read_lines(24), (["x"], True))


class Report(unittest.TestCase):
    def test_partial_read_adds_warn_finding_and_status(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal-hunt-latest.json")
            with mock.patch.object(jh, "REPORTS_DIR", d), mock.patch.object(jh, "REPORT_PATH", path), \
                 mock.patch.object(jh, "read_lines", return_value=(NOISE, False)), \
                 mock.patch.object(jh, "journal_access", return_value="partial"), \
                 mock.patch.object(sys, "argv", ["journald-hunter.py"]), \
                 mock.patch("builtins.print"):
                jh.main()
            with open(path) as f:
                rep = json.load(f)
        self.assertEqual(rep["status"], "warn")
        self.assertEqual(rep["journal_access"], "partial")
        self.assertTrue(any(f["message"].startswith("[hunter] Partial journal read") for f in rep["findings"]))
        self.assertFalse(any(f["message"].startswith("[storage]") for f in rep["findings"]))

    def test_full_read_of_noise_is_ok(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal-hunt-latest.json")
            with mock.patch.object(jh, "REPORTS_DIR", d), mock.patch.object(jh, "REPORT_PATH", path), \
                 mock.patch.object(jh, "read_lines", return_value=(NOISE, False)), \
                 mock.patch.object(jh, "journal_access", return_value="full"), \
                 mock.patch.object(sys, "argv", ["journald-hunter.py"]), \
                 mock.patch("builtins.print"):
                jh.main()
            with open(path) as f:
                rep = json.load(f)
        self.assertEqual(rep["status"], "ok")
        self.assertEqual(rep["findings"], [])


if __name__ == "__main__":
    unittest.main()
