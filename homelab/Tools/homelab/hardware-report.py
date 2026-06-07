#!/usr/bin/env python3
"""
hardware-report.py — Hardware recon as a structured agent report.

JSON port of scripts/hrdwre.sh: CPU, RAM, disk, GPU, thermals, uptime, virtualization,
network interfaces. Warns on high disk usage or high temperatures.

Writes <agent-logs>/hardware-latest.json. Dir from $HL_AGENT_LOGS_DIR
(default ../../../agent-logs relative to this file).
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "hardware-latest.json")

DISK_WARN_PCT = 90
TEMP_WARN_C = 85.0


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def cpu_info():
    info = {}
    for line in _run(["lscpu"]).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() in ("Model name", "Socket(s)", "Core(s) per socket",
                             "Thread(s) per core", "CPU(s)", "CPU max MHz"):
                info[k.strip()] = v.strip()
    return info


def mem_info():
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(("MemTotal", "MemAvailable")):
                    k, v = line.split(":")
                    kb = int(v.strip().split()[0])
                    out[k.strip()] = round(kb / 1024 / 1024, 1)  # GiB
    except FileNotFoundError:
        pass
    return out


def disk_info():
    findings = []
    disks = []
    out = _run(["df", "-P", "-B1", "/"])  # root fs
    lines = out.splitlines()
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 5:
            size, used, avail, pct = parts[1], parts[2], parts[3], parts[4]
            usedp = int(pct.rstrip("%"))
            disks.append({
                "mount": "/", "size_gb": round(int(size) / 1e9, 1),
                "used_gb": round(int(used) / 1e9, 1), "used_pct": usedp,
            })
            if usedp >= DISK_WARN_PCT:
                findings.append({"severity": "warn",
                                 "message": f"Root filesystem {usedp}% full"})
    return disks, findings


def thermals():
    findings = []
    temps = []
    base = "/sys/class/thermal"
    if os.path.isdir(base):
        for zone in sorted(os.listdir(base)):
            tpath = os.path.join(base, zone, "temp")
            typath = os.path.join(base, zone, "type")
            if os.path.isfile(tpath):
                try:
                    with open(tpath) as f:
                        c = int(f.read().strip()) / 1000.0
                    label = "zone"
                    if os.path.isfile(typath):
                        with open(typath) as f:
                            label = f.read().strip()
                    temps.append({"sensor": label, "temp_c": round(c, 1)})
                    if c >= TEMP_WARN_C:
                        findings.append({"severity": "warn",
                                         "message": f"{label} at {c:.1f}°C"})
                except (ValueError, OSError):
                    continue
    return temps, findings


def gpu_info():
    gpus = []
    for line in _run(["lspci"]).splitlines():
        if re.search(r"VGA|3D|Display", line, re.I):
            gpus.append(line.split(":", 2)[-1].strip())
    return gpus


def net_ifaces():
    ifaces = []
    base = "/sys/class/net"
    if os.path.isdir(base):
        for nic in sorted(os.listdir(base)):
            if nic == "lo":
                continue
            ifaces.append(nic)
    return ifaces


def virt_support():
    try:
        with open("/proc/cpuinfo") as f:
            data = f.read()
        return bool(re.search(r"\b(vmx|svm)\b", data))
    except FileNotFoundError:
        return False


def uptime_str():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        d, rem = divmod(int(secs), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h {m}m"
    except (FileNotFoundError, ValueError):
        return "unknown"


def main():
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    disks, disk_findings = disk_info()
    temps, temp_findings = thermals()
    findings = disk_findings + temp_findings
    cpu = cpu_info()
    mem = mem_info()

    status = "warn" if findings else "ok"
    summary = (f"{cpu.get('Model name', 'CPU')} · "
               f"{mem.get('MemTotal', '?')} GiB RAM · "
               f"up {uptime_str()}")
    if findings:
        summary += f" · {len(findings)} flag(s)"

    report = {
        "tool": "hardware-report",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "cpu": cpu,
        "memory_gib": mem,
        "disks": disks,
        "thermals": temps,
        "gpus": gpu_info(),
        "interfaces": net_ifaces(),
        "virtualization": virt_support(),
        "uptime": uptime_str(),
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status})")


if __name__ == "__main__":
    main()
