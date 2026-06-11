#!/usr/bin/env python3
"""
hardware-report.py — deep hardware + health report across all homelab hosts.

Collects CPU, RAM/swap, disks + SMART, thermals, GPU, network interfaces,
virtualization, load, uptime/stability, and kernel err/warn from dmesg — for every
host in HL_HOSTS (opti, rpi, noblenumbat by default), each over SSH so the data
reflects that box. Emits a multi-host report with a per-host "watch list" and a full
markdown `log` for the webapp's full-log viewer.

Writes <agent-logs>/hardware-latest.json + <agent-logs>/hardware-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR; hosts/key from HL_HOSTS /
HL_SSH_KEY (see _hosts.py).

Read-only: never tunes, flashes, or power-cycles hardware. SMART is queried with
`-H -A` reads only (never -t self-tests).
"""

import re

from _report import write_report, now_iso
from _hosts import hosts, ensure_key, run_on, probe, MissingKeyError

DISK_WARN_PCT = 90
TEMP_WARN_C = 85.0
REALLOC_WARN = 10
REPORT_BASE = "hardware-latest"


def _run(host, cmd, timeout=20):
    """Run a command on `host`, return stdout ('' on failure) — mirrors the old local helper."""
    out, rc = run_on(host, cmd, timeout=timeout)
    return out if rc == 0 else ""


def _cat(host, path, timeout=10):
    """Read a remote file's contents ('' if unreadable). Replaces local open()/proc reads."""
    out, rc = run_on(host, ["cat", path], timeout=timeout)
    return out if rc == 0 else ""


def cpu_info(host):
    info = {}
    for line in _run(host, ["lscpu"]).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() in ("Model name", "Socket(s)", "Core(s) per socket",
                             "Thread(s) per core", "CPU(s)", "CPU max MHz"):
                info[k.strip()] = v.strip()
    return info


def cpu_governor(host):
    return _cat(host, "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").strip() or None


def load_avg(host):
    data = _cat(host, "/proc/loadavg")
    return data.split()[:3] if data else []


def mem_info(host):
    out = {}
    data = {}
    for line in _cat(host, "/proc/meminfo").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                data[k.strip()] = int(v.strip().split()[0])  # kB
            except (ValueError, IndexError):
                continue
    for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
        if key in data:
            out[key] = round(data[key] / 1024 / 1024, 1)  # GiB
    return out


def disk_info(host):
    findings = []
    disks = []
    out = _run(host, ["df", "-P", "-B1", "/"])  # root fs
    lines = out.splitlines()
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 5:
            size, used, _avail, pct = parts[1], parts[2], parts[3], parts[4]
            try:
                usedp = int(pct.rstrip("%"))
                disks.append({
                    "mount": "/", "size_gb": round(int(size) / 1e9, 1),
                    "used_gb": round(int(used) / 1e9, 1), "used_pct": usedp,
                })
                if usedp >= DISK_WARN_PCT:
                    findings.append({"severity": "warn",
                                     "message": f"[{host.name}] Root filesystem {usedp}% full"})
            except ValueError:
                pass
    return disks, findings


def block_devices(host):
    """List physical disks (not partitions / loop / mmc-internal partitions)."""
    devs = []
    out = _run(host, ["lsblk", "-dn", "-o", "NAME,TYPE,MODEL,SIZE,ROTA"])
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


def smart_health(host, dev):
    """Read-only SMART summary for a device. Returns dict or None if unavailable."""
    out = _run(host, ["sudo", "-n", "smartctl", "-H", "-A", f"/dev/{dev}"], timeout=20)
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


def thermals(host):
    findings = []
    temps = []
    # Enumerate thermal zones remotely, then read each. One find + a shell loop keeps it to
    # a couple of SSH round-trips instead of one per zone.
    listing = _run(host, ["sh", "-c",
                          'for z in /sys/class/thermal/thermal_zone*; do '
                          'printf "%s\\t%s\\t%s\\n" "$z" '
                          '"$(cat "$z/type" 2>/dev/null)" "$(cat "$z/temp" 2>/dev/null)"; done'])
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[1].strip() or "zone"
        raw = parts[2].strip()
        if not raw:
            continue
        try:
            c = int(raw) / 1000.0
        except ValueError:
            continue
        temps.append({"sensor": label, "temp_c": round(c, 1)})
        if c >= TEMP_WARN_C:
            findings.append({"severity": "warn",
                             "message": f"[{host.name}] {label} at {c:.1f}°C"})
    return temps, findings


def gpu_info(host):
    gpus = []
    for line in _run(host, ["lspci"]).splitlines():
        if re.search(r"VGA|3D|Display", line, re.I):
            gpus.append(line.split(":", 2)[-1].strip())
    return gpus


def net_ifaces(host):
    out = _run(host, ["ls", "/sys/class/net"])
    return sorted(n for n in out.split() if n and n != "lo")


def virt_support(host):
    return bool(re.search(r"\b(vmx|svm)\b", _cat(host, "/proc/cpuinfo")))


def uptime_str(host):
    data = _cat(host, "/proc/uptime")
    try:
        secs = float(data.split()[0])
        d, rem = divmod(int(secs), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h {m}m"
    except (ValueError, IndexError):
        return "unknown"


def dmesg_errors(host):
    out = _run(host, ["sudo", "-n", "dmesg", "--level=err,warn", "-T"], timeout=15)
    if not out:
        return None  # likely needs sudo / unavailable
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-15:]


def collect_host(host):
    """Collect everything for one host over SSH; returns (host_dict, findings, recommendations)."""
    findings = []
    recs = []

    cpu = cpu_info(host)
    gov = cpu_governor(host)
    load = load_avg(host)
    mem = mem_info(host)
    disks, disk_findings = disk_info(host)
    findings += disk_findings
    temps, temp_findings = thermals(host)
    findings += temp_findings

    # SMART per physical disk
    smart = {}
    for dev in block_devices(host):
        name = dev["name"]
        if name.startswith("mmcblk") or name.startswith("loop"):
            continue
        s = smart_health(host, name)
        if s is None:
            recs.append({"severity": "info",
                         "message": f"[{host.name}] SMART for {name} unavailable (needs sudo smartctl); "
                                    f"consider a NOPASSWD rule for `smartctl -H -A`."})
            continue
        smart[name] = s
        if s.get("health") and s["health"].upper() not in ("PASSED", "OK"):
            findings.append({"severity": "critical",
                             "message": f"[{host.name}] SMART health on {name}: {s['health']}"})
        if (s.get("reallocated") or 0) > REALLOC_WARN:
            recs.append({"severity": "warn",
                         "message": f"[{host.name}] {name}: {s['reallocated']} reallocated sectors — aging drive, watch for growth."})
        if (s.get("pending") or 0) > 0:
            findings.append({"severity": "warn",
                             "message": f"[{host.name}] {name}: {s['pending']} pending sectors"})

    # swap pressure
    swap_total = mem.get("SwapTotal", 0)
    swap_used = round(swap_total - mem.get("SwapFree", swap_total), 1) if swap_total else 0
    mem_total = mem.get("MemTotal", 0)
    mem_used = round(mem_total - mem.get("MemAvailable", mem_total), 1) if mem_total else 0
    if mem_total and mem_used / mem_total > 0.9 and swap_total and swap_used / swap_total > 0.5:
        findings.append({"severity": "warn",
                         "message": f"[{host.name}] Memory > 90% used with swap > 50% used"})

    if not temps:
        recs.append({"severity": "info",
                     "message": f"[{host.name}] No thermal sensors reported — consider installing/configuring lm-sensors."})

    dmesg = dmesg_errors(host)
    if dmesg:
        for l in dmesg:
            if re.search(r"hardware error|machine check|MCE|EDAC|disk failure", l, re.I):
                findings.append({"severity": "critical", "message": f"[{host.name}] dmesg: {l.strip()[:160]}"})

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
        "gpus": gpu_info(host),
        "interfaces": net_ifaces(host),
        "virtualization": virt_support(host),
        "uptime": uptime_str(host),
        "dmesg_errors": dmesg if dmesg is not None else "needs sudo",
    }
    cpu_name = cpu.get("Model name", "CPU")
    host_summary = (f"{cpu_name} · {mem.get('MemTotal', '?')} GiB RAM · up {uptime_str(host)}")
    return ({"host": host.name, "status": status, "summary": host_summary, "metrics": metrics},
            findings, recs)


def _host_log(host_dict):
    """Per-host section of the markdown log."""
    m = host_dict["metrics"]
    L = [f"## {host_dict['host']}", "",
         f"- CPU: {m['cpu'].get('Model name', '?')} (governor={m.get('governor') or 'n/a'})",
         f"- Load 1/5/15: {' / '.join(m.get('load') or ['?'])}",
         f"- Memory: {m.get('mem_used_gib', '?')} / {m['memory_gib'].get('MemTotal', '?')} GiB used; "
         f"swap {m.get('swap_used_gib', 0)} / {m['memory_gib'].get('SwapTotal', 0)} GiB",
         f"- Uptime: {m.get('uptime')}",
         f"- Virtualization: {'yes' if m.get('virtualization') else 'no'}",
         ""]
    if m.get("disks"):
        L += ["| Mount | Size GB | Used GB | Used % |", "|---|---|---|---|"]
        for d in m["disks"]:
            L.append(f"| {d['mount']} | {d['size_gb']} | {d['used_gb']} | {d['used_pct']}% |")
        L.append("")
    if m.get("smart"):
        L += ["**SMART**", "",
              "| Disk | Health | Realloc | Pending | Power-on hrs | Temp °C |",
              "|---|---|---|---|---|---|"]
        for dev, s in m["smart"].items():
            L.append(f"| {dev} | {s.get('health', '?')} | {s.get('reallocated', '?')} | "
                     f"{s.get('pending', '?')} | {s.get('power_on_hours', '?')} | {s.get('temp_c', '?')} |")
        L.append("")
    if m.get("thermals"):
        L.append("Temps: " + ", ".join(f"{t['sensor']} {t['temp_c']}°C" for t in m["thermals"]))
        L.append("")
    if m.get("gpus"):
        L.append("GPU: " + "; ".join(m["gpus"]))
        L.append("")
    if isinstance(m.get("dmesg_errors"), list) and m["dmesg_errors"]:
        L += ["Kernel err/warn (dmesg, last lines):", "", "```", *m["dmesg_errors"], "```", ""]
    return L


def build_log(host_dicts, findings, recs):
    L = ["# Hardware Report", "", f"_Generated {now_iso()}_",
         f" · {len(host_dicts)} host(s)", ""]
    for hd in host_dicts:
        L += _host_log(hd)
    L += ["## Concerns / watch list", ""]
    items = findings + recs
    if items:
        for it in items:
            L.append(f"- **{it['severity'].upper()}** — {it['message']}")
    else:
        L.append("- None.")
    L.append("")
    return "\n".join(L)


def main():
    all_hosts = hosts()
    host_dicts = []
    findings = []
    recs = []

    # Fail loud once if the key is missing — otherwise every host would silently fail SSH.
    try:
        ensure_key()
    except MissingKeyError as e:
        findings.append({"severity": "critical", "message": str(e)})
        report = {
            "tool": "hardware-report", "run_at": now_iso(), "status": "critical",
            "summary": "SSH key missing — cannot collect from any host",
            "findings": findings, "recommendations": [], "hosts": [],
            "log": "# Hardware Report\n\n**SSH key missing.** " + str(e),
        }
        latest, dated = write_report(REPORT_BASE, report)
        print(f"Report written: {latest} (status=critical, key missing)")
        return

    for host in all_hosts:
        ok, detail = probe(host)
        if not ok:
            findings.append({"severity": "warn",
                             "message": f"[{host.name}] unreachable over SSH — {detail}"})
            host_dicts.append({"host": host.name, "status": "unknown",
                               "summary": f"unreachable ({detail})", "metrics": {}})
            continue
        hd, hf, hr = collect_host(host)
        host_dicts.append(hd)
        findings += hf
        recs += hr

    if any(f["severity"] == "critical" for f in findings):
        status = "critical"
    elif findings:
        status = "warn"
    else:
        status = "ok"

    reachable = [h for h in host_dicts if h["status"] != "unknown"]
    summary = f"{len(reachable)}/{len(host_dicts)} host(s) reported"
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
        "hosts": host_dicts,
        "log": build_log(host_dicts, findings, recs),
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
