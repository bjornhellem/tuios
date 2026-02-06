#!/usr/bin/env python3
"""Matrix-themed system information TUI for macOS/Linux terminals."""

from __future__ import annotations

import curses
import datetime as dt
import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path

APP_TITLE = "Matrix System Inspector"
SECTIONS = ["Overview", "CPU", "GPU", "Memory", "Disk", "Network", "Processes", "Battery"]


def run_cmd(args: list[str], timeout: float = 2.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except Exception:
        return False, ""
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()
    return True, (proc.stdout or "").strip()


def truncate_text(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def percent_bar(percent: float, width: int = 18) -> str:
    width = max(6, width)
    pct = max(0.0, min(100.0, percent))
    fill = int((pct / 100.0) * width)
    return "[" + ("#" * fill).ljust(width, "-") + "]"


def parse_first_float(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def get_cpu_usage_percent() -> float:
    if platform.system() == "Darwin":
        ok, out = run_cmd(["top", "-l", "1", "-n", "0"], timeout=3)
        if not ok:
            return 0.0
        line = ""
        for raw in out.splitlines():
            if "CPU usage" in raw:
                line = raw
                break
        if not line:
            return 0.0
        user_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*user", line)
        sys_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*sys", line)
        user = float(user_match.group(1)) if user_match else 0.0
        sysv = float(sys_match.group(1)) if sys_match else 0.0
        return max(0.0, min(100.0, user + sysv))

    if Path("/proc/stat").exists():
        first = Path("/proc/stat").read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        parts = [int(v) for v in first.split()[1:8]]
        idle1 = parts[3] + parts[4]
        total1 = sum(parts)
        import time

        time.sleep(0.08)
        second = Path("/proc/stat").read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        parts2 = [int(v) for v in second.split()[1:8]]
        idle2 = parts2[3] + parts2[4]
        total2 = sum(parts2)
        total_delta = total2 - total1
        idle_delta = idle2 - idle1
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - (idle_delta / total_delta)) * 100.0))

    return 0.0


def get_mem_usage() -> tuple[float, str]:
    if platform.system() == "Darwin":
        ok_total, total_out = run_cmd(["sysctl", "-n", "hw.memsize"])
        ok_vm, vm_out = run_cmd(["vm_stat"])
        if not (ok_total and ok_vm):
            return 0.0, "Memory stats unavailable"
        try:
            total = int(total_out.strip())
        except ValueError:
            return 0.0, "Memory stats unavailable"

        page_size = 4096
        page_match = re.search(r"page size of\s+([0-9]+)\s+bytes", vm_out)
        if page_match:
            page_size = int(page_match.group(1))

        page_map: dict[str, int] = {}
        for line in vm_out.splitlines():
            if ":" not in line:
                continue
            key, raw_val = line.split(":", 1)
            raw_digits = re.sub(r"[^0-9]", "", raw_val)
            if not raw_digits:
                continue
            page_map[key.strip().lower()] = int(raw_digits)

        free_pages = page_map.get("pages free", 0) + page_map.get("pages speculative", 0)
        used = max(0, total - (free_pages * page_size))
        percent = (used / total) * 100.0 if total else 0.0
        return percent, f"{used / (1024**3):.2f}G / {total / (1024**3):.2f}G"

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            num = parse_first_float(raw)
            if num is not None:
                values[key] = int(num)
        total_kb = values.get("MemTotal", 0)
        avail_kb = values.get("MemAvailable", 0)
        used_kb = max(0, total_kb - avail_kb)
        pct = (used_kb / total_kb) * 100.0 if total_kb else 0.0
        return pct, f"{used_kb / (1024**2):.2f}G / {total_kb / (1024**2):.2f}G"

    return 0.0, "Memory stats unavailable"


def get_disk_usage() -> tuple[float, str]:
    disk = shutil.disk_usage("/")
    used = disk.used
    total = disk.total
    pct = (used / total) * 100.0 if total else 0.0
    return pct, f"{used / (1024**3):.2f}G / {total / (1024**3):.2f}G"


def get_cpu_static_info() -> list[str]:
    lines = [
        f"Processor: {platform.processor() or 'n/a'}",
        f"Arch: {platform.machine()}",
        f"Logical cores: {os.cpu_count() or 'n/a'}",
    ]
    if platform.system() == "Darwin":
        for key, label in (
            ("machdep.cpu.brand_string", "Brand"),
            ("hw.physicalcpu", "Physical cores"),
            ("hw.logicalcpu", "Logical cores (sysctl)"),
            ("hw.cpufrequency", "CPU frequency (Hz)"),
        ):
            ok, out = run_cmd(["sysctl", "-n", key])
            if ok and out:
                lines.append(f"{label}: {out}")
    return lines


def get_gpu_info() -> list[str]:
    if platform.system() == "Darwin":
        ok, out = run_cmd(["system_profiler", "SPDisplaysDataType"], timeout=8)
        if not ok or not out:
            return ["GPU details unavailable"]
        keep = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            wanted = (
                "Chipset Model",
                "Type",
                "Bus",
                "VRAM",
                "Vendor",
                "Device ID",
                "Metal",
                "Resolution",
            )
            if any(stripped.startswith(item) for item in wanted):
                keep.append(stripped)
        return keep[:60] if keep else ["GPU details unavailable"]

    ok, out = run_cmd(["lspci"], timeout=4)
    if ok and out:
        lines = [ln for ln in out.splitlines() if "VGA" in ln or "3D" in ln or "Display" in ln]
        return lines[:20] if lines else ["GPU details unavailable"]
    return ["GPU details unavailable"]


def get_memory_details() -> list[str]:
    if platform.system() == "Darwin":
        lines: list[str] = []
        ok, out = run_cmd(["vm_stat"])
        if ok and out:
            lines.append("vm_stat:")
            lines.extend(["  " + ln for ln in out.splitlines()[:30]])
        ok_s, out_s = run_cmd(["sysctl", "-n", "hw.memsize"])
        if ok_s:
            lines.append(f"Total bytes: {out_s}")
        return lines or ["Memory details unavailable"]

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        return meminfo.read_text(encoding="utf-8", errors="ignore").splitlines()[:80]
    return ["Memory details unavailable"]


def get_disk_details() -> list[str]:
    lines: list[str] = []
    ok_df, out_df = run_cmd(["df", "-h"])
    if ok_df and out_df:
        lines.append("Filesystem usage:")
        lines.extend(out_df.splitlines()[:40])

    if platform.system() == "Darwin":
        ok_d, out_d = run_cmd(["diskutil", "list"], timeout=6)
        if ok_d and out_d:
            lines.append("")
            lines.append("diskutil list:")
            lines.extend(out_d.splitlines()[:80])

    return lines or ["Disk details unavailable"]


def get_network_details() -> list[str]:
    lines: list[str] = []
    if platform.system() == "Darwin":
        ok_if, out_if = run_cmd(["ifconfig"], timeout=5)
        if ok_if and out_if:
            lines.append("ifconfig:")
            lines.extend(out_if.splitlines()[:120])
        ok_r, out_r = run_cmd(["netstat", "-rn"])
        if ok_r and out_r:
            lines.append("")
            lines.append("Routing table:")
            lines.extend(out_r.splitlines()[:40])
    else:
        ok_ip, out_ip = run_cmd(["ip", "addr"], timeout=4)
        if ok_ip and out_ip:
            lines.append("ip addr:")
            lines.extend(out_ip.splitlines()[:100])
    return lines or ["Network details unavailable"]


def get_process_details() -> list[str]:
    ok, out = run_cmd(["ps", "-Ao", "pid,ppid,pcpu,pmem,user,comm", "-r"], timeout=4)
    if not ok or not out:
        return ["Process details unavailable"]
    lines = out.splitlines()
    return ["Top processes by CPU:"] + lines[:60]


def get_battery_details() -> list[str]:
    if platform.system() == "Darwin":
        ok, out = run_cmd(["pmset", "-g", "batt"])
        if ok and out:
            lines = ["Battery:"] + out.splitlines()
        else:
            lines = ["Battery details unavailable"]

        ok_t, out_t = run_cmd(["pmset", "-g", "therm"])
        if ok_t and out_t:
            lines.extend(["", "Thermals:"] + out_t.splitlines())
        return lines

    power_supply = Path("/sys/class/power_supply")
    if power_supply.exists():
        lines = ["Power supplies:"]
        for item in sorted(power_supply.iterdir()):
            lines.append(str(item.name))
            for field in ("status", "capacity", "voltage_now", "current_now"):
                p = item / field
                if p.exists():
                    lines.append(f"  {field}: {p.read_text(encoding='utf-8', errors='ignore').strip()}")
        return lines

    return ["Battery details unavailable"]


def get_overview_lines(usage: dict[str, tuple[float, str]]) -> list[str]:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"Timestamp: {now}",
        f"Hostname: {socket.gethostname()}",
        f"OS: {platform.system()} {platform.release()} ({platform.version()})",
        f"Kernel: {platform.platform()}",
        f"Python: {platform.python_version()}",
        "",
        "Usage snapshot:",
        f"  CPU: {usage['cpu'][0]:5.1f}%   {usage['cpu'][1]}",
        f"  Memory: {usage['mem'][0]:5.1f}%   {usage['mem'][1]}",
        f"  Disk(/): {usage['disk'][0]:5.1f}%   {usage['disk'][1]}",
    ]

    ok_u, out_u = run_cmd(["uptime"])
    if ok_u and out_u:
        lines.extend(["", f"Uptime: {out_u}"])

    return lines


def build_section(section: str, usage: dict[str, tuple[float, str]], cache: dict[str, list[str]]) -> list[str]:
    if section == "Overview":
        return get_overview_lines(usage)
    if section == "CPU":
        lines = ["CPU details:"] + get_cpu_static_info()
        ok, out = run_cmd(["uptime"])
        if ok and out:
            lines.extend(["", f"Load: {out}"])
        lines.extend(["", "Realtime CPU:", f"Usage: {usage['cpu'][0]:.1f}%", f"Bar: {percent_bar(usage['cpu'][0], 30)}"])
        return lines
    if section == "GPU":
        if section not in cache:
            cache[section] = get_gpu_info()
        return ["GPU details:"] + cache[section]
    if section == "Memory":
        lines = ["Memory details:", f"Realtime: {usage['mem'][0]:.1f}% ({usage['mem'][1]})", ""]
        if section not in cache:
            cache[section] = get_memory_details()
        lines.extend(cache[section])
        return lines
    if section == "Disk":
        lines = ["Disk details:", f"Realtime / usage: {usage['disk'][0]:.1f}% ({usage['disk'][1]})", ""]
        if section not in cache:
            cache[section] = get_disk_details()
        lines.extend(cache[section])
        return lines
    if section == "Network":
        if section not in cache:
            cache[section] = get_network_details()
        return ["Network details:"] + cache[section]
    if section == "Processes":
        return get_process_details()
    if section == "Battery":
        return get_battery_details()
    return ["No data"]


def draw_boxed(stdscr: curses.window, title: str) -> None:
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(1))
    stdscr.box()
    stdscr.addnstr(0, 2, f" {title} ", w - 4)
    stdscr.attroff(curses.color_pair(1))


def draw_usage_panel(stdscr: curses.window, usage: dict[str, tuple[float, str]]) -> None:
    h, w = stdscr.getmaxyx()
    panel_w = min(46, max(34, w // 3))
    panel_h = 7
    x = w - panel_w - 2
    y = 1

    if x < 2 or y + panel_h >= h - 1:
        return

    for row in range(panel_h):
        stdscr.addnstr(y + row, x, " " * panel_w, panel_w, curses.color_pair(1))

    stdscr.addnstr(y, x + 1, " Live Usage ", panel_w - 2, curses.color_pair(3))

    labels = [("CPU", usage["cpu"]), ("MEM", usage["mem"]), ("DSK", usage["disk"])]
    for idx, (label, (pct, text)) in enumerate(labels):
        row = y + 1 + idx * 2
        bar = percent_bar(pct, width=max(10, panel_w - 21))
        line = f"{label} {pct:5.1f}% {bar}"
        stdscr.addnstr(row, x + 1, truncate_text(line, panel_w - 2), panel_w - 2, curses.color_pair(2))
        stdscr.addnstr(row + 1, x + 1, truncate_text(text, panel_w - 2), panel_w - 2, curses.color_pair(2))


def draw_ui(
    stdscr: curses.window,
    selected_section: int,
    lines: list[str],
    scroll: int,
    status: str,
    usage: dict[str, tuple[float, str]],
) -> None:
    draw_boxed(stdscr, APP_TITLE)
    h, w = stdscr.getmaxyx()

    nav_w = max(18, min(24, w // 4))
    content_x = nav_w + 3
    content_w = max(10, w - content_x - 2)
    body_top = 2
    body_bottom = h - 4
    body_h = max(1, body_bottom - body_top)

    stdscr.vline(1, nav_w + 1, curses.ACS_VLINE, h - 3)
    stdscr.addnstr(1, 2, "Sections", nav_w - 1, curses.color_pair(3))

    for idx, section in enumerate(SECTIONS):
        y = body_top + idx
        if y >= body_bottom:
            break
        marker = ">" if idx == selected_section else " "
        color = curses.color_pair(3) if idx == selected_section else curses.color_pair(2)
        stdscr.addnstr(y, 2, f"{marker} {section}", nav_w - 1, color)

    stdscr.addnstr(1, content_x, f"{SECTIONS[selected_section]} details", content_w, curses.color_pair(3))

    visible = lines[scroll : scroll + body_h]
    for i, line in enumerate(visible):
        y = body_top + i
        if y >= body_bottom:
            break
        stdscr.addnstr(y, content_x, truncate_text(line, content_w), content_w, curses.color_pair(2))

    draw_usage_panel(stdscr, usage)

    controls = "UP/DOWN select section  J/K scroll  PgUp/PgDn scroll page  R refresh  Q quit"
    stdscr.addnstr(h - 2, 2, truncate_text(controls, w - 4), w - 4, curses.color_pair(3))
    stdscr.addnstr(h - 3, 2, truncate_text(status, w - 4), w - 4, curses.color_pair(2))
    stdscr.refresh()


def collect_usage() -> dict[str, tuple[float, str]]:
    cpu_pct = get_cpu_usage_percent()
    mem_pct, mem_text = get_mem_usage()
    disk_pct, disk_text = get_disk_usage()
    return {
        "cpu": (cpu_pct, f"CPU sampled at {dt.datetime.now().strftime('%H:%M:%S')}"),
        "mem": (mem_pct, mem_text),
        "disk": (disk_pct, disk_text),
    }


def app(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Same matrix palette as the other local TUIs.
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)

    stdscr.keypad(True)
    stdscr.timeout(1000)

    selected = 0
    scroll = 0
    cache: dict[str, list[str]] = {}
    usage = collect_usage()
    section_lines = build_section(SECTIONS[selected], usage, cache)
    status = f"Loaded {SECTIONS[selected]}"

    while True:
        max_scroll = max(0, len(section_lines) - max(1, stdscr.getmaxyx()[0] - 6))
        scroll = max(0, min(scroll, max_scroll))
        draw_ui(stdscr, selected, section_lines, scroll, status, usage)

        key = stdscr.getch()

        if key == -1:
            usage = collect_usage()
            if SECTIONS[selected] in ("Processes", "Battery", "Overview", "CPU"):
                section_lines = build_section(SECTIONS[selected], usage, cache)
            continue

        if key in (ord("q"), ord("Q")):
            return

        if key in (ord("r"), ord("R")):
            usage = collect_usage()
            cache.clear()
            section_lines = build_section(SECTIONS[selected], usage, cache)
            scroll = 0
            status = f"Refreshed {SECTIONS[selected]}"
            continue

        if key == curses.KEY_UP:
            selected = (selected - 1) % len(SECTIONS)
            scroll = 0
            section_lines = build_section(SECTIONS[selected], usage, cache)
            status = f"Selected: {SECTIONS[selected]}"
            continue

        if key == curses.KEY_DOWN:
            selected = (selected + 1) % len(SECTIONS)
            scroll = 0
            section_lines = build_section(SECTIONS[selected], usage, cache)
            status = f"Selected: {SECTIONS[selected]}"
            continue

        if key in (ord("j"), curses.KEY_NPAGE):
            step = max(1, (stdscr.getmaxyx()[0] - 6) if key == curses.KEY_NPAGE else 1)
            scroll = min(max_scroll, scroll + step)
            continue

        if key in (ord("k"), curses.KEY_PPAGE):
            step = max(1, (stdscr.getmaxyx()[0] - 6) if key == curses.KEY_PPAGE else 1)
            scroll = max(0, scroll - step)
            continue


def main() -> None:
    try:
        curses.wrapper(app)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except curses.error:
        print("Terminal too small or unsupported for curses UI.")


if __name__ == "__main__":
    main()
