"""Bounded, local-only detail collector for the Monitor workspace.

This module deliberately returns raw counters.  The webapp owns intervals, shared
sampling and history; keeping this side stateless means it cannot invent a spike
after the agent restarts.  It is imported by ``hl-arch-agent.py`` and installed beside
it as ``/usr/local/bin/monitor.py``.
"""

from __future__ import annotations

import glob
import os
import signal
import time
from typing import Any

try:
    import pwd
except ImportError:  # Windows checkout validation; production hosts are Linux.
    pwd = None

SCHEMA_VERSION = 1
PROTECTED_NAMES = {"hl-arch-agent.py", "intel_gpu_top"}


def _read(path: str, default: str | None = None) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def _int(path: str) -> int | None:
    try:
        return int(_read(path) or "")
    except ValueError:
        return None


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, value = line.partition(":")
                fields = value.split()
                if fields and fields[0].isdigit():
                    out[key] = int(fields[0]) * 1024
    except OSError:
        pass
    return out


def _cpu() -> dict[str, Any]:
    rows: dict[str, dict[str, int]] = {}
    names = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice")
    try:
        with open("/proc/stat") as f:
            for line in f:
                fields = line.split()
                if not fields or not fields[0].startswith("cpu"):
                    continue
                values = [int(v) for v in fields[1:]]
                rows[fields[0]] = {name: values[i] if i < len(values) else 0 for i, name in enumerate(names)}
    except (OSError, ValueError):
        pass
    load = _read("/proc/loadavg", "") or ""
    loads = []
    for value in load.split()[:3]:
        try:
            loads.append(float(value))
        except ValueError:
            loads.append(None)
    return {"counters": rows.get("cpu"), "cores": {k: v for k, v in rows.items() if k != "cpu"}, "load": loads}


def _memory() -> dict[str, int | None]:
    m = _meminfo()
    total = m.get("MemTotal")
    available = m.get("MemAvailable")
    return {
        "total_bytes": total, "available_bytes": available,
        "used_bytes": total - available if total is not None and available is not None else None,
        "free_bytes": m.get("MemFree"), "cache_bytes": m.get("Cached"),
        "buffers_bytes": m.get("Buffers"), "swap_total_bytes": m.get("SwapTotal"),
        "swap_free_bytes": m.get("SwapFree"),
    }


def _network() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, _, rest = line.partition(":")
                fields = rest.split()
                if len(fields) < 16:
                    continue
                out[name.strip()] = {
                    "rx_bytes": int(fields[0]), "rx_packets": int(fields[1]), "rx_errors": int(fields[2]), "rx_drops": int(fields[3]),
                    "tx_bytes": int(fields[8]), "tx_packets": int(fields[9]), "tx_errors": int(fields[10]), "tx_drops": int(fields[11]),
                }
    except (OSError, ValueError):
        pass
    return out


def _disks() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                fields = line.split()
                if len(fields) < 14:
                    continue
                name = fields[2]
                # Partitions duplicate the parent disk counters; capacity still comes
                # from mounts, so I/O is intentionally physical-device only here.
                if os.path.exists(f"/sys/block/{name}/partition") or not os.path.exists(f"/sys/block/{name}"):
                    continue
                out[name] = {
                    "reads": int(fields[3]), "read_sectors": int(fields[5]), "read_ms": int(fields[6]),
                    "writes": int(fields[7]), "write_sectors": int(fields[9]), "write_ms": int(fields[10]),
                    "busy_ms": int(fields[12]),
                }
    except (OSError, ValueError):
        pass
    return out


def _mounts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    ignored = {"tmpfs", "devtmpfs", "proc", "sysfs", "cgroup2", "overlay", "squashfs", "efivarfs"}
    try:
        with open("/proc/mounts") as f:
            for line in f:
                source, mount, fs_type, *_ = line.split()
                if mount in seen or fs_type in ignored:
                    continue
                seen.add(mount)
                try:
                    st = os.statvfs(mount)
                except OSError:
                    continue
                out.append({"source": source, "mount": mount, "fs_type": fs_type,
                            "total_bytes": st.f_frsize * st.f_blocks,
                            "available_bytes": st.f_frsize * st.f_bavail})
    except OSError:
        pass
    return out


def _temperature() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in glob.glob("/sys/class/hwmon/hwmon*/temp*_input") + glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        value = _int(path)
        if value is None or not 0 < value < 130000:
            continue
        base = os.path.dirname(path)
        label = _read(path.replace("_input", "_label")) or _read(os.path.join(base, "name")) or os.path.basename(path)
        out.append({"label": label, "celsius": round(value / 1000, 1)})
    return out


def _power() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in glob.glob("/sys/class/powercap/intel-rapl*/energy_uj"):
        value = _int(path)
        if value is not None:
            out.append({"name": _read(os.path.join(os.path.dirname(path), "name")) or os.path.basename(os.path.dirname(path)),
                        "energy_uj": value, "max_energy_range_uj": _int(os.path.join(os.path.dirname(path), "max_energy_range_uj"))})
    return out


def _battery() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for base in glob.glob("/sys/class/power_supply/BAT*"):
        out.append({"name": os.path.basename(base), "status": _read(os.path.join(base, "status")),
                    "capacity_pct": _int(os.path.join(base, "capacity")), "energy_now_uwh": _int(os.path.join(base, "energy_now")),
                    "energy_full_uwh": _int(os.path.join(base, "energy_full")), "power_uw": _int(os.path.join(base, "power_now"))})
    return out


def _gpu() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in glob.glob("/sys/class/drm/card[0-9]*"):
        if "-" in os.path.basename(card):
            continue
        dev = os.path.join(card, "device")
        driver = os.path.basename(os.path.realpath(os.path.join(dev, "driver")))
        vendor = _read(os.path.join(dev, "vendor"))
        device = _read(os.path.join(dev, "device"))
        if not driver:
            continue
        out.append({"id": os.path.basename(card), "driver": driver, "vendor": vendor, "device": device,
                    "clock_current_mhz": _int(os.path.join(dev, "gt_cur_freq_mhz")),
                    "clock_active_mhz": _int(os.path.join(dev, "gt_act_freq_mhz")),
                    "busy_pct": _int(os.path.join(dev, "gpu_busy_percent")),
                    "utilization_status": "supported" if driver == "i915" else "unsupported",
                    "memory_kind": "shared" if driver in ("i915", "v3d", "vc4-drm") else None})
    return out


def _boot_id() -> str | None:
    return _read("/proc/sys/kernel/random/boot_id")


def _uptime() -> float | None:
    try:
        return float((_read("/proc/uptime") or "").split()[0])
    except (IndexError, ValueError):
        return None


def _process(pid: int) -> dict[str, Any] | None:
    stat = _read(f"/proc/{pid}/stat")
    if not stat or ") " not in stat:
        return None
    comm_end = stat.rfind(")")
    name = stat[stat.find("(") + 1:comm_end]
    fields = stat[comm_end + 2:].split()
    if len(fields) < 20:
        return None
    status = _read(f"/proc/{pid}/status", "") or ""
    status_map = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    try:
        uid = int(status_map.get("Uid", "0").split()[0])
        user = pwd.getpwuid(uid).pw_name if pwd else str(uid)
    except (KeyError, ValueError):
        user = str(status_map.get("Uid", "?").split()[0] if status_map.get("Uid") else "?")
    cmd = (_read(f"/proc/{pid}/cmdline", "") or "").replace("\x00", " ").strip() or name
    io: dict[str, int] = {}
    for line in (_read(f"/proc/{pid}/io", "") or "").splitlines():
        key, _, value = line.partition(":")
        try:
            io[key] = int(value.strip())
        except ValueError:
            pass
    return {"pid": pid, "program": name, "command": cmd[:2048], "state": fields[0], "ppid": int(fields[1]),
            "utime": int(fields[11]), "stime": int(fields[12]), "threads": int(fields[17]), "start_ticks": int(fields[19]),
            "rss_pages": int(fields[21]) if len(fields) > 21 else 0, "user": user,
            "read_bytes": io.get("read_bytes", 0), "write_bytes": io.get("write_bytes", 0)}


def processes(limit: int = 500) -> list[dict[str, Any]]:
    try:
        entries = os.listdir("/proc")
    except OSError:
        entries = []
    rows = [_process(int(n)) for n in entries if n.isdigit()]
    result = [row for row in rows if row and row["state"] != "Z"]
    return sorted(result, key=lambda row: row["pid"])[:max(1, min(limit, 2000))]


def capabilities() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "boot_id": _boot_id(),
            "sections": {"cpu": "supported", "memory": "supported", "disks": "supported", "network": "supported",
                         "processes": "supported", "sensors": "supported", "power": "supported", "battery": "supported" if glob.glob("/sys/class/power_supply/BAT*") else "unsupported",
                         "gpu": "supported" if glob.glob("/sys/class/drm/card[0-9]*") else "unsupported"},
            "signals": ["SIGHUP", "SIGINT", "SIGTERM", "SIGKILL", "SIGSTOP", "SIGCONT", "SIGUSR1", "SIGUSR2"],
            "gpus": _gpu()}


def snapshot(include_processes: bool = True) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "measured_at": time.time(), "monotonic_s": time.monotonic(), "uptime_s": _uptime(),
            "boot_id": _boot_id(), "cpu": _cpu(), "memory": _memory(), "network": _network(), "disks": _disks(),
            "mounts": _mounts(), "temperatures": _temperature(), "power": _power(), "battery": _battery(), "gpu": _gpu(),
            "processes": processes() if include_processes else []}


def process_detail(pid: int, boot_id: str | None = None, start_ticks: int | None = None) -> tuple[int, dict[str, Any]]:
    if boot_id and boot_id != _boot_id():
        return 409, {"error": "host rebooted; refresh the process list"}
    row = _process(pid)
    if not row:
        return 404, {"error": "process exited"}
    if start_ticks is not None and row["start_ticks"] != start_ticks:
        return 409, {"error": "PID was reused; refresh the process list"}
    return 200, {"boot_id": _boot_id(), "process": row}


def send_signal(pid: int, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    name = body.get("signal_name")
    if name not in capabilities()["signals"]:
        return 400, {"error": "unsupported signal"}
    if body.get("boot_id") != _boot_id():
        return 409, {"error": "host rebooted; refresh the process list"}
    row = _process(pid)
    if not row or row["start_ticks"] != body.get("start_ticks"):
        return 409, {"error": "process identity changed; refresh the process list"}
    if pid == 1 or row["program"] in PROTECTED_NAMES:
        return 403, {"error": "protected process"}
    try:
        fd = os.pidfd_open(pid)
        try:
            signal.pidfd_send_signal(fd, getattr(signal, name))
        finally:
            os.close(fd)
    except (AttributeError, OSError) as exc:
        return 409, {"error": f"signal was not delivered: {exc}"}
    return 200, {"ok": True, "pid": pid, "signal_name": name, "boot_id": _boot_id(), "start_ticks": row["start_ticks"]}
