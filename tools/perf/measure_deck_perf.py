#!/usr/bin/env python3
"""Measure StreamDeckGB runtime performance.

Collects the metrics the deck-frame-pipeline work is judged on, for a running
StreamDeckGB process:

  - process CPU % (all threads, averaged over the window)
  - CPU package power (RAPL "package-0", averaged Watts)  [PPT proxy]
  - CPU temperature (k10temp Tctl, average + max)
  - AMD GPU fence errors (new "Fence fallback timer expired" dmesg lines)
  - per-frame render/write times from the app's own [perf] / [usb-stall] logs
    (only present when the app runs with --debug)

Usage:

  # Measure a running instance for N seconds (default 60):
  python3 tools/perf/measure_deck_perf.py --pid 12345 --seconds 300 --label after --out after.json

  # Auto-find the StreamDeckGB process:
  python3 tools/perf/measure_deck_perf.py --seconds 300 --label after

  # Compare two runs:
  python3 tools/perf/measure_deck_perf.py --compare before.json after.json

The 5-minute criterion from the perf report: run with --seconds 300.
"""
import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time

RAPL_ENERGY = "/sys/class/powercap/intel-rapl:0/energy_uj"
RAPL_MAX_ENERGY = "/sys/class/powercap/intel-rapl:0/max_energy_range_uj"
RAPL_POWER = "/sys/class/powercap/intel-rapl:0/power"
HWMON = "/sys/class/hwmon"
FENCE_PATTERN = re.compile(r"Fence fallback timer expired")

# App log locations (fork's --devel run uses the flatpak-style data dir)
LOG_CANDIDATES = [
    os.path.expanduser("~/.var/app/com.core447.StreamController/data/logs/logs.log"),
    os.path.expanduser("~/.var/app/com.gb.streamdeckgb/data/logs/logs.log"),
]

PERF_LINE = re.compile(r"\[perf\]|\[perf-light\]")
STALL_LINE = re.compile(r"\[usb-stall\]")
MEDIA_TASK_LINE = re.compile(r"\[media-task\]")
PAGE_SWITCH_LINE = re.compile(r"\[page-switch\]")


def read_rapl_max_energy():
    try:
        with open(RAPL_MAX_ENERGY) as f:
            return int(f.read().strip())
    except (OSError, ValueError, IOError):
        return None


def find_streamdeckgb_pid():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm == "StreamDeckGB":
                return int(pid)
        except (OSError, IOError):
            continue
    return None


def read_rapl_energy():
    try:
        with open(RAPL_ENERGY) as f:
            return int(f.read().strip())
    except (OSError, ValueError, IOError):
        pass
    # energy_uj is often root-only; retry via passwordless sudo.
    try:
        out = subprocess.run(["sudo", "-n", "cat", RAPL_ENERGY], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return int(out.stdout.strip())
    except Exception:
        pass
    return None


def read_rapl_power_instant():
    try:
        with open(RAPL_POWER) as f:
            return int(f.read().strip()) / 1_000_000.0
    except (OSError, ValueError, IOError):
        return None


def read_cpu_temp():
    for hw in glob.glob(os.path.join(HWMON, "hwmon*")):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() == "k10temp":
                    with open(os.path.join(hw, "temp1_input")) as f:
                        return int(f.read().strip()) / 1000.0
        except (OSError, ValueError, IOError):
            continue
    return None


def count_fence_errors():
    try:
        out = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=20)
        return len(FENCE_PATTERN.findall(out.stdout))
    except Exception:
        return None


def app_log_path():
    for path in LOG_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def count_log_events(path, start_offset):
    """Count [perf]/[usb-stall]/[media-task]/[page-switch] lines appended to the
    log since start_offset (bytes). Returns counts and the new end offset."""
    counts = {"perf": 0, "usb-stall": 0, "media-task": 0, "page-switch": 0}
    try:
        size = os.path.getsize(path)
        if size <= start_offset:
            return counts, size
        with open(path, "r", errors="replace") as f:
            f.seek(start_offset)
            data = f.read()
        for line in data.splitlines():
            if PERF_LINE.search(line):
                counts["perf"] += 1
            if STALL_LINE.search(line):
                counts["usb-stall"] += 1
            if MEDIA_TASK_LINE.search(line):
                counts["media-task"] += 1
            if PAGE_SWITCH_LINE.search(line):
                counts["page-switch"] += 1
        return counts, size
    except OSError:
        return counts, start_offset


def sample_process_cpu(pid):
    """Return (utime, stime) ticks for the process (all threads)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        # After the comm field: state(3) ppid(4) ... utime(14) stime(15)
        return int(fields[11]), int(fields[12])
    except (OSError, ValueError, IndexError, IOError):
        return None


def measure(pid, seconds, label=""):
    start = time.monotonic()

    cpu0 = sample_process_cpu(pid)
    energy0 = read_rapl_energy()
    temp_samples = []
    power_samples = []
    fence0 = count_fence_errors()

    log_path = app_log_path()
    log_offset = os.path.getsize(log_path) if log_path else 0

    interval = max(0.5, min(2.0, seconds / 20.0))
    next_sample = start
    while time.monotonic() - start < seconds:
        now = time.monotonic()
        if now >= next_sample:
            next_sample += interval
            t = read_cpu_temp()
            if t is not None:
                temp_samples.append(t)
            p = read_rapl_power_instant()
            if p is not None:
                power_samples.append(p)
        time.sleep(0.2)

    cpu1 = sample_process_cpu(pid)
    energy1 = read_rapl_energy()
    fence1 = count_fence_errors()
    elapsed = time.monotonic() - start

    result = {
        "label": label or pid,
        "pid": pid,
        "window_s": round(elapsed, 1),
        "cpu_percent": None,
        "rapl_package_watts_avg": None,
        "cpu_temp_avg_c": None,
        "cpu_temp_max_c": None,
        "gpu_fence_errors_new": None,
        "app_log": {"path": log_path, "perf": 0, "usb-stall": 0, "media-task": 0, "page-switch": 0},
    }

    if cpu0 is not None and cpu1 is not None:
        total_ticks = (cpu1[0] - cpu0[0]) + (cpu1[1] - cpu0[1])
        hz = os.sysconf("SC_CLK_TCK")
        result["cpu_percent"] = round(total_ticks / hz / elapsed * 100.0, 1)

    if energy0 is not None and energy1 is not None:
        d = energy1 - energy0
        max_energy = read_rapl_max_energy()
        if d < 0:
            # Counter wrapped (max_energy_range_uj, often 2^36, not 2^64).
            d += max_energy or 2**64
        result["rapl_package_watts_avg"] = round(d / 1_000_000.0 / elapsed, 1)

    if temp_samples:
        result["cpu_temp_avg_c"] = round(statistics.mean(temp_samples), 1)
        result["cpu_temp_max_c"] = round(max(temp_samples), 1)

    if fence0 is not None and fence1 is not None:
        result["gpu_fence_errors_new"] = max(0, fence1 - fence0)

    if log_path:
        counts, log_offset = count_log_events(log_path, log_offset)
        result["app_log"].update(counts)

    return result


def print_report(r):
    print(f"label                : {r['label']}")
    print(f"pid                  : {r['pid']}")
    print(f"window               : {r['window_s']} s")
    print(f"CPU                  : {r['cpu_percent']} % (all threads, avg)")
    print(f"package power (RAPL) : {r['rapl_package_watts_avg']} W (avg)")
    print(f"CPU temp (Tctl)      : {r['cpu_temp_avg_c']} C avg / {r['cpu_temp_max_c']} C max")
    print(f"GPU fence errors     : {r['gpu_fence_errors_new']} new")
    log = r.get("app_log") or {}
    if log.get("path"):
        print(f"app log              : {log['path']}")
        print(f"  [perf] lines       : {log['perf']}")
        print(f"  [usb-stall] lines  : {log['usb-stall']}")
        print(f"  [media-task] lines : {log['media-task']}")
        print(f"  [page-switch]      : {log['page-switch']}")


def compare(a, b):
    keys = [
        ("cpu_percent", "CPU %"),
        ("rapl_package_watts_avg", "package power W"),
        ("cpu_temp_avg_c", "CPU temp avg C"),
        ("cpu_temp_max_c", "CPU temp max C"),
        ("gpu_fence_errors_new", "GPU fence errors"),
        ("app_log.perf", "app [perf] lines"),
        ("app_log.usb-stall", "app [usb-stall] lines"),
    ]
    print(f"{'metric':<22}{'before':>12}{'after':>12}{'delta':>12}")
    for key, name in keys:
        def get(r):
            if "." in key:
                return (r.get("app_log") or {}).get(key.split(".")[1])
            return r.get(key)
        va = get(a)
        vb = get(b)
        if va is None and vb is None:
            continue
        da = "n/a" if va is None else f"{va:.1f}" if isinstance(va, float) else str(va)
        db = "n/a" if vb is None else f"{vb:.1f}" if isinstance(vb, float) else str(vb)
        delta = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = vb - va
            sign = "+" if d > 0 else ""
            delta = f"{sign}{d:.1f}"
        print(f"{name:<22}{da:>12}{db:>12}{delta:>12}")


def main():
    ap = argparse.ArgumentParser(description="Measure StreamDeckGB runtime performance")
    ap.add_argument("--pid", type=int, default=None, help="Process id (default: auto-find StreamDeckGB)")
    ap.add_argument("--seconds", type=float, default=60.0, help="Sampling window in seconds")
    ap.add_argument("--label", default="", help="Label for the report")
    ap.add_argument("--out", default=None, help="Save report JSON to this path")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="Compare two report JSONs")
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0]) as f:
            before = json.load(f)
        with open(args.compare[1]) as f:
            after = json.load(f)
        compare(before, after)
        return

    pid = args.pid or find_streamdeckgb_pid()
    if pid is None:
        print("Could not find a running StreamDeckGB process. Pass --pid.", file=sys.stderr)
        sys.exit(1)

    print(f"Measuring pid {pid} for {args.seconds}s ...", file=sys.stderr)
    report = measure(pid, args.seconds, label=args.label)
    print_report(report)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved report to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
