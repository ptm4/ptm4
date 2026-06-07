#!/usr/bin/env python3
"""
hardware-report.py — deep hardware + health report as a structured agent report.

Collects CPU, RAM/swap, disks + SMART, thermals, GPU, network interfaces,
virtualization, load, uptime/stability, and kernel err/warn from dmesg. Emits a
multi-host-ready report (currently the local host) with a recommendations/"watch
list" section and a full markdown `log` for the webapp's full-log viewer.

Writes <agent-logs>/hardware-latest.json + <agent-logs>/hardware-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR.

Read-only: never tunes, flashes, or power-cycles hardware. SMART is queried with
`-H -A` reads only (never -t self-tests).
"""

import os
import re
import socket
import subprocess

from _report import write_report, now_iso

DISK_WARN_PCT = 90
TEMP_WARN_C = 85.0
REALLOC_WARN = 10
REPORT_BASE = "hardware-latest"


def _run(cmd, timeout=20):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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


def cpu_governor():
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            return f.read().strip()
    except OSError:
        return None


def load_avg():
    try:
        with open("/proc/loadavg") as f:
            return f.read().split()[:3]
    except OSError:
        return []


def mem_info():
    out = {}
    try:
        with open("/proc/meminfo") as f:
            data = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip()] = int(v.strip().split()[0])  # kB
        for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            if key in data:
                out[key] = round(data[key] / 1024 / 1024, 1)  # GiB
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
            size, used, _avail, pct = parts[1], parts[2], parts[3], parts[4]
            usedp = int(pct.rstrip("%"))
            disks.append({
                "mount": "/", "size_gb": round(int(size) / 1e9, 1),
                "used_gb": round(int(used) / 1e9, 1), "used_pct": usedp,
            })
            if usedp >= DISK_WARN_PCT:
                findings.append({"severity": "warn",
                                 "message": f"Root filesystem {usedp}% full"})
    return disks, findings


def block_devices():
    """List physical disks (not partitions / loop / mmc-internal partitions)."""
    devs = []
    out = _run(["lsblk", "-dn", "-o", "NAME,TYPE,MODEL,SIZE,ROTA"])
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 2 and parts[1] == "disk":
            devs.append({
                "name": parts[0],
                "model": (parts[2] if len(parts) > 2 else "").strip(),
                "size": parts[3] if len(parts) > 3 else "",
                "rotational": parts[4].strip() == "1" if len(parts) > 4 else None,
            })
    return devs


def smart_health(dev):
    """Read-only SMART summary for a device. Returns dict or None if unavailable."""
    out = _run(["sudo", "-n", "smartctl", "-H", "-A", f"/dev/{dev}"], timeout=20)
    if not out:
        return None
    health = None
    m = re.search(r"overall-health.*?:\s*(\S+)", out, re.I)
    if m:
        health = m.group(1)
    realloc = pending = poh = temp = None
    for line in out.splitlines():
        if "Reallocated_Sector" in line:
            realloc = _last_int(line)
        elif "Pending_Sector" in line or "Current_Pending" in line:
            pending = _last_int(line)
        elif "Power_On_Hours" in line:
            poh = _last_int(line)
        elif "Temperature_Celsius" in line or "Airflow_Temperature" in line:
            temp = _last_int(line)
    return {"health": health, "reallocated": realloc, "pending": pending,
            "power_on_hours": poh, "temp_c": temp}


def _last_int(line):
    nums = re.findall(r"\d+", line)
    return int(nums[-1]) if nums else None


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
            if nic != "lo":
                ifaces.append(nic)
    return ifaces


def virt_support():
    try:
        with open("/proc/cpuinfo") as f:
            return bool(re.search(r"\b(vmx|svm)\b", f.read()))
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


def dmesg_errors():
    out = _run(["sudo", "-n", "dmesg", "--level=err,warn", "-T"], timeout=15)
    if not out:
        return None  # likely needs sudo / unavailable
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-15:]


def collect_host():
    """Collect everything for the local host; returns (host_dict, findings, recommendations)."""
    host = socket.gethostname()
    findings = []
    recs = []

    cpu = cpu_info()
    gov = cpu_governor()
    load = load_avg()
    mem = mem_info()
    disks, disk_findings = disk_info()
    findings += disk_findings
    temps, temp_findings = thermals()
    findings += temp_findings

    # SMART per physical disk
    smart = {}
    for dev in block_devices():
        name = dev["name"]
        if name.startswith("mmcblk") or name.startswith("loop"):
            continue
        s = smart_health(name)
        if s is None:
            recs.append({"severity": "info",
                         "message": f"SMART for {name} unavailable (needs sudo smartctl); "
                                    f"consider a NOPASSWD rule for `smartctl -H -A`."})
            continue
        smart[name] = s
        if s.get("health") and s["health"].upper() not in ("PASSED", "OK"):
            findings.append({"severity": "critical",
                             "message": f"SMART health on {name}: {s['health']}"})
        if (s.get("reallocated") or 0) > REALLOC_WARN:
            recs.append({"severity": "warn",
                         "message": f"{name}: {s['reallocated']} reallocated sectors — aging drive, watch for growth."})
        if (s.get("pending") or 0) > 0:
            findings.append({"severity": "warn",
                             "message": f"{name}: {s['pending']} pending sectors"})

    # swap pressure
    swap_total = mem.get("SwapTotal", 0)
    swap_used = round(swap_total - mem.get("SwapFree", swap_total), 1) if swap_total else 0
    mem_total = mem.get("MemTotal", 0)
    mem_used = round(mem_total - mem.get("MemAvailable", mem_total), 1) if mem_total else 0
    if mem_total and mem_used / mem_total > 0.9 and swap_total and swap_used / swap_total > 0.5:
        findings.append({"severity": "warn",
                         "message": "Memory > 90% used with swap > 50% used"})

    if not temps:
        recs.append({"severity": "info",
                     "message": "No thermal sensors reported — consider installing/configuring lm-sensors."})

    dmesg = dmesg_errors()
    if dmesg:
        for l in dmesg:
            if re.search(r"hardware error|machine check|MCE|EDAC|disk failure", l, re.I):
                findings.append({"severity": "critical", "message": f"dmesg: {l.strip()[:160]}"})

    status = "ok"
    if any(f["severity"] in ("critical",) for f in findings):
        status = "critical"
    elif findings:
        status = "warn"

    metrics = {
        "cpu": cpu,
        "governor": gov,
        "load": load,
        "memory_gib": mem,
        "mem_used_gib": mem_used,
        "swap_used_gib": swap_used,
        "disks": disks,
        "smart": smart,
        "thermals": temps,
        "gpus": gpu_info(),
        "interfaces": net_ifaces(),
        "virtualization": virt_support(),
        "uptime": uptime_str(),
        "dmesg_errors": dmesg if dmesg is not None else "needs sudo",
    }
    cpu_name = cpu.get("Model name", "CPU")
    host_summary = (f"{cpu_name} · {mem.get('MemTotal', '?')} GiB RAM · up {uptime_str()}")
    return ({"host": host, "status": status, "summary": host_summary, "metrics": metrics},
            findings, recs)


def build_log(host, findings, recs):
    m = host["metrics"]
    L = [f"# Hardware Report — {host['host']}", "",
         f"_Generated {now_iso()}_", "",
         "## Health summary", "",
         f"- CPU: {m['cpu'].get('Model name', '?')} (governor={m.get('governor') or 'n/a'})",
         f"- Load 1/5/15: {' / '.join(m.get('load') or ['?'])}",
         f"- Memory: {m.get('mem_used_gib', '?')} / {m['memory_gib'].get('MemTotal', '?')} GiB used; "
         f"swap {m.get('swap_used_gib', 0)} / {m['memory_gib'].get('SwapTotal', 0)} GiB",
         f"- Uptime: {m.get('uptime')}",
         f"- Virtualization: {'yes' if m.get('virtualization') else 'no'}",
         ""]
    if m.get("disks"):
        L.append("## Filesystems")
        L.append("")
        L.append("| Mount | Size GB | Used GB | Used % |")
        L.append("|---|---|---|---|")
        for d in m["disks"]:
            L.append(f"| {d['mount']} | {d['size_gb']} | {d['used_gb']} | {d['used_pct']}% |")
        L.append("")
    if m.get("smart"):
        L.append("## SMART")
        L.append("")
        L.append("| Disk | Health | Realloc | Pending | Power-on hrs | Temp °C |")
        L.append("|---|---|---|---|---|---|")
        for dev, s in m["smart"].items():
            L.append(f"| {dev} | {s.get('health', '?')} | {s.get('reallocated', '?')} | "
                     f"{s.get('pending', '?')} | {s.get('power_on_hours', '?')} | {s.get('temp_c', '?')} |")
        L.append("")
    if m.get("thermals"):
        L.append("## Temperatures")
        L.append("")
        for t in m["thermals"]:
            L.append(f"- {t['sensor']}: {t['temp_c']}°C")
        L.append("")
    if m.get("gpus"):
        L.append("## GPU")
        L.append("")
        for g in m["gpus"]:
            L.append(f"- {g}")
        L.append("")
    if isinstance(m.get("dmesg_errors"), list) and m["dmesg_errors"]:
        L.append("## Kernel err/warn (dmesg, last lines)")
        L.append("")
        L.append("```")
        L += m["dmesg_errors"]
        L.append("```")
        L.append("")
    L.append("## Concerns / watch list")
    L.append("")
    items = findings + recs
    if items:
        for it in items:
            L.append(f"- **{it['severity'].upper()}** — {it['message']}")
    else:
        L.append("- None.")
    L.append("")
    return "\n".join(L)


def main():
    host, findings, recs = collect_host()
    status = host["status"]

    summary = host["summary"]
    flag_n = len(findings) + len([r for r in recs if r["severity"] != "info"])
    if flag_n:
        summary += f" · {flag_n} flag(s)"

    report = {
        "tool": "hardware-report",
        "run_at": now_iso(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "recommendations": recs,
        "hosts": [host],
        "log": build_log(host, findings, recs),
        # back-compat top-level convenience keys (mirror the single host's metrics)
        "cpu": host["metrics"]["cpu"],
        "disks": host["metrics"]["disks"],
        "thermals": host["metrics"]["thermals"],
        "uptime": host["metrics"]["uptime"],
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
