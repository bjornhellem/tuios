#!/usr/bin/env python3
"""Matrix-themed TUI wrapper for nmap on macOS/Linux terminals."""

from __future__ import annotations

import csv
import curses
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


PREDEFINED_SCANS = [
    ("Quick scan (fast)", ["-T4", "-F"]),
    ("Intense scan", ["-T4", "-A", "-v"]),
    ("Ping sweep (host discovery)", ["-sn"]),
    ("Service/version scan", ["-sV", "--top-ports", "1000"]),
    ("Common UDP ports", ["-sU", "--top-ports", "200"]),
]


@dataclass
class ScanResult:
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    parsed: dict[str, Any]


def check_nmap_available() -> tuple[bool, str]:
    nmap_path = shutil.which("nmap")
    if not nmap_path:
        return False, "nmap was not found in PATH. Install it (e.g. `brew install nmap`)."

    try:
        proc = subprocess.run(
            [nmap_path, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        return False, f"nmap exists but failed to execute: {exc}"

    if proc.returncode != 0:
        return False, f"nmap exists but is not executable (exit {proc.returncode})."
    first_line = (proc.stdout or "").splitlines()[0] if proc.stdout else "nmap detected"
    return True, first_line


def parse_nmap_xml(xml_path: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scan_info": {},
        "hosts": [],
        "stats": {},
    }

    if not os.path.exists(xml_path) or os.path.getsize(xml_path) == 0:
        return result

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return result

    result["scan_info"] = {
        "scanner": root.attrib.get("scanner"),
        "args": root.attrib.get("args"),
        "start": root.attrib.get("startstr"),
        "version": root.attrib.get("version"),
    }

    for host in root.findall("host"):
        host_data: dict[str, Any] = {
            "status": None,
            "addresses": [],
            "hostnames": [],
            "ports": [],
        }

        status = host.find("status")
        if status is not None:
            host_data["status"] = status.attrib.get("state")

        for addr in host.findall("address"):
            host_data["addresses"].append(
                {"addr": addr.attrib.get("addr"), "type": addr.attrib.get("addrtype")}
            )

        for hostname in host.findall("hostnames/hostname"):
            host_data["hostnames"].append(hostname.attrib.get("name"))

        for port in host.findall("ports/port"):
            state_el = port.find("state")
            service_el = port.find("service")
            host_data["ports"].append(
                {
                    "protocol": port.attrib.get("protocol"),
                    "port": int(port.attrib.get("portid", "0")),
                    "state": state_el.attrib.get("state") if state_el is not None else None,
                    "reason": state_el.attrib.get("reason") if state_el is not None else None,
                    "service": service_el.attrib.get("name") if service_el is not None else None,
                    "product": service_el.attrib.get("product") if service_el is not None else None,
                    "version": service_el.attrib.get("version") if service_el is not None else None,
                }
            )

        result["hosts"].append(host_data)

    finished = root.find("runstats/finished")
    hosts = root.find("runstats/hosts")
    result["stats"] = {
        "finished": finished.attrib.get("timestr") if finished is not None else None,
        "elapsed": finished.attrib.get("elapsed") if finished is not None else None,
        "up": hosts.attrib.get("up") if hosts is not None else None,
        "down": hosts.attrib.get("down") if hosts is not None else None,
        "total": hosts.attrib.get("total") if hosts is not None else None,
    }
    return result


def export_json(scan_result: ScanResult, output_path: str) -> None:
    payload = {
        "command": scan_result.command,
        "returncode": scan_result.returncode,
        "stdout": scan_result.stdout,
        "stderr": scan_result.stderr,
        "parsed": scan_result.parsed,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def export_csv(scan_result: ScanResult, output_path: str) -> None:
    rows = []
    for host in scan_result.parsed.get("hosts", []):
        host_id = ""
        if host.get("hostnames"):
            host_id = host["hostnames"][0]
        elif host.get("addresses"):
            host_id = host["addresses"][0].get("addr", "")

        for port in host.get("ports", []):
            rows.append(
                {
                    "host": host_id,
                    "status": host.get("status"),
                    "protocol": port.get("protocol"),
                    "port": port.get("port"),
                    "state": port.get("state"),
                    "reason": port.get("reason"),
                    "service": port.get("service"),
                    "product": port.get("product"),
                    "version": port.get("version"),
                }
            )

    fields = [
        "host",
        "status",
        "protocol",
        "port",
        "state",
        "reason",
        "service",
        "product",
        "version",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def draw_boxed(stdscr: curses.window, title: str) -> None:
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(1))
    stdscr.box()
    stdscr.addnstr(0, 2, f" {title} ", w - 4)
    stdscr.attroff(curses.color_pair(1))


def prompt_input(stdscr: curses.window, label: str) -> str:
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h - 3, 2, " " * (w - 4), w - 4)
    stdscr.addnstr(h - 3, 2, label[: w - 6], w - 6)
    stdscr.attroff(curses.color_pair(2))
    curses.echo()
    curses.curs_set(1)
    raw = stdscr.getstr(h - 2, 2, w - 4)
    curses.noecho()
    curses.curs_set(0)
    return raw.decode("utf-8", errors="ignore").strip()


def run_nmap_scan(args: list[str]) -> ScanResult:
    fd, xml_path = tempfile.mkstemp(prefix="nmap_tui_", suffix=".xml")
    os.close(fd)

    cmd = ["nmap", *args, "-oX", xml_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    parsed = parse_nmap_xml(xml_path)

    try:
        os.remove(xml_path)
    except OSError:
        pass

    return ScanResult(
        command=cmd,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        parsed=parsed,
    )


def load_targets_from_file(path: str) -> tuple[list[str], str | None]:
    expanded = str(Path(path).expanduser())
    if not os.path.exists(expanded):
        return [], f"Target file not found: {expanded}"
    if not os.path.isfile(expanded):
        return [], f"Not a file: {expanded}"

    try:
        with open(expanded, "r", encoding="utf-8", errors="ignore") as f:
            targets = [line.strip() for line in f if line.strip()]
    except OSError as exc:
        return [], f"Failed to read target file: {exc}"

    if not targets:
        return [], "Target file is empty."
    return targets, None


def prompt_predefined_targets(stdscr: curses.window, scan_name: str) -> tuple[list[str], str | None]:
    draw_boxed(stdscr, "Target Input")
    h, w = stdscr.getmaxyx()
    stdscr.addnstr(2, 2, f"Scan: {scan_name}", w - 4, curses.color_pair(2))
    stdscr.addnstr(4, 2, "Choose targets: 1) Single IP/host/CIDR  2) Read targets from file", w - 4, curses.color_pair(2))
    stdscr.addnstr(5, 2, "Press B to cancel.", w - 4, curses.color_pair(2))
    stdscr.refresh()

    key = stdscr.getch()
    if key in (ord("b"), ord("B")):
        return [], "Scan canceled."

    if key == ord("1"):
        target = prompt_input(stdscr, f"Target for '{scan_name}' (IP/host/CIDR): ")
        if not target:
            return [], "Scan canceled (no target)."
        return [target], None

    if key == ord("2"):
        path = prompt_input(stdscr, "Path to target file (one target per line): ")
        if not path:
            return [], "Scan canceled (no file path)."
        targets, err = load_targets_from_file(path)
        if err:
            return [], err
        return targets, None

    return [], "Scan canceled."


def run_ssh_session(stdscr: curses.window, target: str) -> int:
    # Temporarily suspend curses so the interactive ssh session can own the terminal.
    curses.def_prog_mode()
    curses.endwin()
    try:
        print(f"\n[SSH] Starting: ssh {target}")
        print("[SSH] Close with `exit`/`logout` or force-close with Enter then `~.`\n")
        proc = subprocess.run(["ssh", target], check=False)
        return proc.returncode
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.clear()
        stdscr.refresh()


def show_lines(stdscr: curses.window, title: str, lines: list[str]) -> str:
    offset = 0
    while True:
        draw_boxed(stdscr, title)
        h, w = stdscr.getmaxyx()
        body_h = h - 4

        visible = lines[offset : offset + body_h]
        for i, line in enumerate(visible, start=1):
            stdscr.addnstr(i, 2, line, w - 4, curses.color_pair(2))

        footer = "UP/DOWN scroll  S save  B back"
        stdscr.addnstr(h - 2, 2, footer, w - 4, curses.color_pair(3))
        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("b"), ord("B")):
            return "back"
        if key in (ord("s"), ord("S")):
            return "save"
        if key == curses.KEY_UP and offset > 0:
            offset -= 1
        elif key == curses.KEY_DOWN and offset + body_h < len(lines):
            offset += 1


def _host_ip(host: dict[str, Any]) -> str:
    addresses = host.get("addresses", [])
    for addr in addresses:
        if addr.get("type") == "ipv4":
            return addr.get("addr", "unknown")
    if addresses:
        return addresses[0].get("addr", "unknown")
    return "unknown"


def _host_label(host: dict[str, Any]) -> str:
    ip = _host_ip(host)
    hostname = ""
    if host.get("hostnames"):
        hostname = host["hostnames"][0] or ""
    if hostname and hostname != ip:
        return f"{ip} ({hostname})"
    return ip


def build_host_details_lines(scan_result: ScanResult, host: dict[str, Any]) -> list[str]:
    lines = [
        f"Command: {' '.join(shlex.quote(x) for x in scan_result.command)}",
        f"Exit code: {scan_result.returncode}",
        "",
        f"Selected host: {_host_label(host)}",
        f"Status: {host.get('status') or '-'}",
    ]

    hostnames = ", ".join(filter(None, host.get("hostnames", []))) or "-"
    lines.append(f"Hostnames: {hostnames}")
    lines.append("Addresses:")
    addresses = host.get("addresses", [])
    if not addresses:
        lines.append("  - none")
    else:
        for addr in addresses:
            lines.append(f"  - {addr.get('type')}: {addr.get('addr')}")

    ports = sorted(host.get("ports", []), key=lambda p: (p.get("port", 0), p.get("protocol", "")))
    open_ports = [p for p in ports if p.get("state") == "open"]
    lines.extend(
        [
            "",
            f"Ports: {len(ports)} total, {len(open_ports)} open",
            "",
            "Open ports:",
        ]
    )
    if not open_ports:
        lines.append("  - none")
    else:
        for port in open_ports:
            svc = port.get("service") or "unknown"
            product = port.get("product") or ""
            version = port.get("version") or ""
            detail = " ".join(x for x in [product, version] if x).strip()
            suffix = f" [{detail}]" if detail else ""
            lines.append(f"  - {port.get('port')}/{port.get('protocol')} {svc}{suffix}")

    lines.extend(["", "All discovered ports:"])
    if not ports:
        lines.append("  - none")
    else:
        for port in ports:
            lines.append(
                f"  - {port.get('port')}/{port.get('protocol')} {port.get('state')} "
                f"(service={port.get('service') or 'unknown'}, reason={port.get('reason') or '-'})"
            )
    return lines


def show_host_split_view(stdscr: curses.window, scan_result: ScanResult) -> str:
    hosts = scan_result.parsed.get("hosts", [])
    if not hosts:
        return show_lines(stdscr, "Scan Result", build_result_lines(scan_result))

    selected = 0
    left_offset = 0
    right_offset = 0
    focus = "left"

    while True:
        h, w = stdscr.getmaxyx()
        body_h = h - 4
        left_w = max(30, min(48, w // 3))
        sep_x = left_w + 1

        details = build_host_details_lines(scan_result, hosts[selected])
        max_right_offset = max(0, len(details) - body_h)

        if selected < left_offset:
            left_offset = selected
        elif selected >= left_offset + body_h:
            left_offset = selected - body_h + 1

        draw_boxed(stdscr, "Scan Result")
        stdscr.vline(1, sep_x, curses.ACS_VLINE, h - 3)
        hosts_header = "Hosts <" if focus == "left" else "Hosts"
        details_header = "Host Details <" if focus == "right" else "Host Details"
        stdscr.addnstr(1, 2, hosts_header, left_w - 1, curses.color_pair(3))
        stdscr.addnstr(1, sep_x + 2, details_header, w - sep_x - 4, curses.color_pair(3))

        for i in range(body_h - 1):
            host_idx = left_offset + i
            y = 2 + i
            if host_idx >= len(hosts):
                break
            label = _host_label(hosts[host_idx])
            color = curses.color_pair(3) if host_idx == selected else curses.color_pair(2)
            prefix = ">" if host_idx == selected else " "
            stdscr.addnstr(y, 2, f"{prefix} {label}", left_w - 1, color)

        visible_right = details[right_offset : right_offset + body_h - 1]
        for i, line in enumerate(visible_right):
            y = 2 + i
            stdscr.addnstr(y, sep_x + 2, line, w - sep_x - 4, curses.color_pair(2))

        footer = "LEFT/RIGHT switch pane  UP/DOWN move  H ssh  S save  B back"
        stdscr.addnstr(h - 2, 2, footer, w - 4, curses.color_pair(3))
        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("b"), ord("B")):
            return "back"
        if key in (ord("s"), ord("S")):
            return "save"
        if key in (ord("h"), ord("H")):
            return f"ssh:{_host_ip(hosts[selected])}"
        if key == curses.KEY_LEFT:
            focus = "left"
        elif key == curses.KEY_RIGHT:
            focus = "right"
        elif focus == "left" and key == curses.KEY_UP and selected > 0:
            selected -= 1
            right_offset = 0
        elif focus == "left" and key == curses.KEY_DOWN and selected < len(hosts) - 1:
            selected += 1
            right_offset = 0
        elif focus == "right" and key == curses.KEY_UP:
            right_offset = max(0, right_offset - 1)
        elif focus == "right" and key == curses.KEY_DOWN:
            right_offset = min(max_right_offset, right_offset + 1)
        elif key == curses.KEY_PPAGE:
            right_offset = max(0, right_offset - (body_h - 1))
        elif key == curses.KEY_NPAGE:
            right_offset = min(max_right_offset, right_offset + (body_h - 1))


def save_scan_flow(stdscr: curses.window, scan_result: ScanResult) -> None:
    draw_boxed(stdscr, "Save Scan")
    h, w = stdscr.getmaxyx()
    stdscr.addnstr(2, 2, "Choose format: 1) JSON  2) CSV", w - 4, curses.color_pair(2))
    stdscr.addnstr(3, 2, "Press B to cancel.", w - 4, curses.color_pair(2))
    stdscr.refresh()

    key = stdscr.getch()
    if key in (ord("b"), ord("B")):
        return

    if key == ord("1"):
        ext = "json"
        exporter = export_json
    elif key == ord("2"):
        ext = "csv"
        exporter = export_csv
    else:
        return

    default_name = f"nmap_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    path_input = prompt_input(stdscr, f"Path [{default_name}]: ")
    path = path_input or default_name
    out = str(Path(path).expanduser())

    try:
        exporter(scan_result, out)
        msg = f"Saved: {out}"
    except Exception as exc:  # pragma: no cover - user I/O errors
        msg = f"Save failed: {exc}"

    draw_boxed(stdscr, "Save Scan")
    stdscr.addnstr(2, 2, msg, w - 4, curses.color_pair(2))
    stdscr.addnstr(4, 2, "Press any key...", w - 4, curses.color_pair(3))
    stdscr.refresh()
    stdscr.getch()


def build_result_lines(scan_result: ScanResult) -> list[str]:
    lines = [
        f"Command: {' '.join(shlex.quote(x) for x in scan_result.command)}",
        f"Exit code: {scan_result.returncode}",
        "",
    ]

    stats = scan_result.parsed.get("stats", {})
    if stats:
        lines.extend(
            [
                f"Hosts up/down/total: {stats.get('up')}/{stats.get('down')}/{stats.get('total')}",
                f"Finished: {stats.get('finished')}  Elapsed: {stats.get('elapsed')}s",
                "",
            ]
        )

    hosts = scan_result.parsed.get("hosts", [])
    if hosts:
        lines.append("Parsed hosts/ports:")
        for host in hosts:
            names = ", ".join(filter(None, host.get("hostnames", [])))
            addrs = ", ".join([a.get("addr", "") for a in host.get("addresses", [])])
            host_label = names or addrs or "unknown"
            lines.append(f"- {host_label} [{host.get('status')}]")
            for port in host.get("ports", []):
                if port.get("state") == "open":
                    svc = port.get("service") or "?"
                    lines.append(f"    {port.get('port')}/{port.get('protocol')} open ({svc})")
        lines.append("")

    if scan_result.stdout:
        lines.append("Raw nmap output:")
        lines.extend(scan_result.stdout.splitlines())

    if scan_result.stderr:
        lines.extend(["", "stderr:", *scan_result.stderr.splitlines()])

    if not scan_result.stdout and not scan_result.stderr and not hosts:
        lines.append("No output captured.")

    return lines


def draw_menu(stdscr: curses.window, selected: int, status_line: str) -> None:
    draw_boxed(stdscr, "Nmap Matrix TUI")
    h, w = stdscr.getmaxyx()

    stdscr.addnstr(1, 2, "Predefined scans", w - 4, curses.color_pair(3))
    row = 2
    for idx, (name, _) in enumerate(PREDEFINED_SCANS):
        prefix = ">" if idx == selected else " "
        color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
        stdscr.addnstr(row, 2, f"{prefix} {idx + 1}. {name}", w - 4, color)
        row += 1

    options_start = row + 1
    custom_idx = len(PREDEFINED_SCANS)
    quit_idx = custom_idx + 1

    custom_prefix = ">" if selected == custom_idx else " "
    quit_prefix = ">" if selected == quit_idx else " "

    stdscr.addnstr(
        options_start,
        2,
        f"{custom_prefix} C. Custom scan parameters",
        w - 4,
        curses.color_pair(3) if selected == custom_idx else curses.color_pair(2),
    )
    stdscr.addnstr(
        options_start + 1,
        2,
        f"{quit_prefix} Q. Quit",
        w - 4,
        curses.color_pair(3) if selected == quit_idx else curses.color_pair(2),
    )

    stdscr.addnstr(h - 3, 2, "UP/DOWN to choose, ENTER to run", w - 4, curses.color_pair(3))
    stdscr.addnstr(h - 2, 2, status_line[: w - 4], w - 4, curses.color_pair(2))
    stdscr.refresh()


def app(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Matrix-like palette: bright green text on black, with a highlighted accent.
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)

    selected = 0
    status = "Ready"

    while True:
        draw_menu(stdscr, selected, status)
        key = stdscr.getch()

        max_idx = len(PREDEFINED_SCANS) + 1
        if key == curses.KEY_UP:
            selected = (selected - 1) % (max_idx + 1)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % (max_idx + 1)
        elif key in (ord("q"), ord("Q")):
            return
        elif key in (curses.KEY_ENTER, 10, 13):
            if selected == len(PREDEFINED_SCANS) + 1:
                return

            if selected < len(PREDEFINED_SCANS):
                name, base_args = PREDEFINED_SCANS[selected]
                targets, err = prompt_predefined_targets(stdscr, name)
                if err:
                    status = err
                    continue
                args = [*base_args, *targets]
            else:
                raw = prompt_input(stdscr, "Custom nmap args (example: -sV 192.168.1.0/24): ")
                if not raw:
                    status = "Scan canceled (no args)."
                    continue
                args = shlex.split(raw)
                file_path = prompt_input(stdscr, "Optional target file path (blank to skip): ")
                if file_path:
                    targets, err = load_targets_from_file(file_path)
                    if err:
                        status = err
                        continue
                    args.extend(targets)

            draw_boxed(stdscr, "Running Scan")
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(2, 2, f"Running: nmap {' '.join(args)}", w - 4, curses.color_pair(2))
            stdscr.addnstr(4, 2, "Please wait...", w - 4, curses.color_pair(3))
            stdscr.refresh()

            scan_result = run_nmap_scan(args)

            while True:
                action = show_host_split_view(stdscr, scan_result)
                if action == "save":
                    save_scan_flow(stdscr, scan_result)
                    status = "Scan complete; result saved or ready to save."
                elif action.startswith("ssh:"):
                    ssh_target = action.split(":", 1)[1]
                    rc = run_ssh_session(stdscr, ssh_target)
                    status = f"SSH session ended for {ssh_target} (exit {rc})."
                else:
                    status = f"Scan complete (exit {scan_result.returncode})."
                    break


def main() -> None:
    ok, msg = check_nmap_available()
    if not ok:
        print(f"[ERROR] {msg}")
        raise SystemExit(1)

    try:
        curses.wrapper(app)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except curses.error:
        print("Terminal too small or unsupported for curses UI.")


if __name__ == "__main__":
    main()
