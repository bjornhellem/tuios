#!/usr/bin/env python3
"""Matrix-themed SSH connection manager TUI for macOS/Linux terminals."""

from __future__ import annotations

import curses
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import menu_bar

APP_TITLE = "SSH Matrix TUI"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent
HOSTS_FILE = Path(__file__).resolve().parent / "ssh_hosts.txt"


@dataclass
class SSHConnection:
    name: str
    host: str
    user: str
    port: int
    key_path: str

    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def summary(self) -> str:
        key_label = self.key_path if self.key_path else "default-key"
        return f"{self.name} | {self.target()}:{self.port} | {key_label}"


def check_ssh_available() -> tuple[bool, str]:
    ssh_path = shutil.which("ssh")
    if not ssh_path:
        return False, "ssh was not found in PATH. Install OpenSSH client first."

    proc = subprocess.run([ssh_path, "-V"], capture_output=True, text=True, check=False)
    version = (proc.stderr or proc.stdout or "ssh detected").strip()
    if proc.returncode != 0:
        return False, f"ssh exists but failed to execute (exit {proc.returncode})."
    return True, version


def sanitize_field(value: str) -> str:
    return value.replace("\t", " ").strip()


def ensure_hosts_file() -> None:
    if HOSTS_FILE.exists():
        return
    HOSTS_FILE.write_text(
        "# SSH Connection Manager hosts\n"
        "# Fields (tab-separated): name\thost\tuser\tport\tkey_path\n",
        encoding="utf-8",
    )


def load_connections() -> tuple[list[SSHConnection], str | None]:
    ensure_hosts_file()
    conns: list[SSHConnection] = []
    bad_lines = 0

    for raw_line in HOSTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = raw_line.rstrip("\n").split("\t")
        if len(parts) != 5:
            bad_lines += 1
            continue

        name, host, user, port_raw, key_path = [sanitize_field(part) for part in parts]
        if not host:
            bad_lines += 1
            continue

        try:
            port = int(port_raw)
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            bad_lines += 1
            continue

        conns.append(
            SSHConnection(
                name=name or host,
                host=host,
                user=user,
                port=port,
                key_path=key_path,
            )
        )

    warning = None
    if bad_lines:
        warning = f"Skipped {bad_lines} malformed line(s) in {HOSTS_FILE.name}."
    return conns, warning


def save_connections(connections: list[SSHConnection]) -> None:
    lines = [
        "# SSH Connection Manager hosts",
        "# Fields (tab-separated): name\thost\tuser\tport\tkey_path",
    ]
    for conn in connections:
        lines.append(
            "\t".join(
                [
                    sanitize_field(conn.name),
                    sanitize_field(conn.host),
                    sanitize_field(conn.user),
                    str(conn.port),
                    sanitize_field(conn.key_path),
                ]
            )
        )

    HOSTS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def prompt_default(stdscr: curses.window, label: str, current: str) -> str:
    value = prompt_input(stdscr, f"{label} [{current}]: ")
    return value if value else current


def parse_port(port_raw: str) -> tuple[int | None, str | None]:
    try:
        port = int(port_raw)
        if 1 <= port <= 65535:
            return port, None
        return None, "Port must be between 1 and 65535."
    except ValueError:
        return None, "Port must be a number."


def unique_name(connections: list[SSHConnection], base_name: str) -> str:
    existing = {conn.name for conn in connections}
    if base_name not in existing:
        return base_name

    index = 2
    while True:
        candidate = f"{base_name}-{index}"
        if candidate not in existing:
            return candidate
        index += 1


def run_ssh_session(stdscr: curses.window, conn: SSHConnection) -> int:
    cmd = ["ssh", "-p", str(conn.port)]
    if conn.key_path:
        cmd.extend(["-i", str(Path(conn.key_path).expanduser())])
    cmd.append(conn.target())

    curses.def_prog_mode()
    curses.endwin()
    try:
        print(f"\n[SSH] Starting: {' '.join(cmd)}")
        print("[SSH] Exit with `exit`/`logout` or force-close with Enter then `~.`\n")
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.clear()
        stdscr.refresh()


def draw_menu(stdscr: curses.window, connections: list[SSHConnection], selected: int, status: str) -> None:
    draw_boxed(stdscr, "SSH Matrix TUI")
    h, w = stdscr.getmaxyx()

    stdscr.addnstr(1, 2, f"Saved hosts file: {HOSTS_FILE.name}", w - 4, curses.color_pair(3))

    body_h = max(1, h - 9)
    start = 0
    if selected >= body_h:
        start = selected - body_h + 1

    if not connections:
        stdscr.addnstr(3, 2, "No saved hosts. Press A to add or Q for quick connect.", w - 4, curses.color_pair(2))
    else:
        for row in range(body_h):
            idx = start + row
            if idx >= len(connections):
                break
            conn = connections[idx]
            prefix = ">" if idx == selected else " "
            color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
            stdscr.addnstr(3 + row, 2, f"{prefix} {conn.summary()}", w - 4, color)

    controls = "UP/DOWN move  ENTER connect  A add  Q quick-connect  E edit  D delete  X exit"
    stdscr.addnstr(h - 3, 2, controls, w - 4, curses.color_pair(3))
    stdscr.addnstr(h - 2, 2, status[: w - 4], w - 4, curses.color_pair(2))
    stdscr.refresh()


def add_connection_flow(stdscr: curses.window, connections: list[SSHConnection]) -> tuple[list[SSHConnection], str]:
    host = prompt_input(stdscr, "Host/IP: ")
    if not host:
        return connections, "Add canceled (no host)."

    name = prompt_input(stdscr, f"Name [{host}]: ") or host
    user = prompt_input(stdscr, "User (optional): ")
    port_raw = prompt_input(stdscr, "Port [22]: ") or "22"
    key_path = prompt_input(stdscr, "SSH key path (optional, e.g. ~/.ssh/id_ed25519): ")

    port, err = parse_port(port_raw)
    if err or port is None:
        return connections, err or "Invalid port."

    safe_name = unique_name(connections, sanitize_field(name) or host)
    new_conn = SSHConnection(
        name=safe_name,
        host=sanitize_field(host),
        user=sanitize_field(user),
        port=port,
        key_path=sanitize_field(key_path),
    )
    updated = [*connections, new_conn]
    save_connections(updated)
    return updated, f"Saved host: {new_conn.summary()}"


def quick_connect_flow(stdscr: curses.window, connections: list[SSHConnection]) -> tuple[list[SSHConnection], SSHConnection | None, str]:
    host = prompt_input(stdscr, "Quick connect host/IP: ")
    if not host:
        return connections, None, "Quick connect canceled (no host)."

    user = prompt_input(stdscr, "User (optional): ")
    port_raw = prompt_input(stdscr, "Port [22]: ") or "22"
    key_path = prompt_input(stdscr, "SSH key path (optional): ")

    port, err = parse_port(port_raw)
    if err or port is None:
        return connections, None, err or "Invalid port."

    host = sanitize_field(host)
    user = sanitize_field(user)
    key_path = sanitize_field(key_path)

    for conn in connections:
        if conn.host == host and conn.user == user and conn.port == port and conn.key_path == key_path:
            return connections, conn, f"Using existing saved host: {conn.name}"

    base_name = host
    new_conn = SSHConnection(
        name=unique_name(connections, base_name),
        host=host,
        user=user,
        port=port,
        key_path=key_path,
    )
    updated = [*connections, new_conn]
    save_connections(updated)
    return updated, new_conn, f"Saved and connecting: {new_conn.name}"


def edit_connection_flow(stdscr: curses.window, connections: list[SSHConnection], selected: int) -> tuple[list[SSHConnection], str]:
    if not connections:
        return connections, "No hosts to edit."

    conn = connections[selected]
    name = prompt_default(stdscr, "Name", conn.name)
    host = prompt_default(stdscr, "Host/IP", conn.host)
    user = prompt_default(stdscr, "User", conn.user)
    port_raw = prompt_default(stdscr, "Port", str(conn.port))
    key_path = prompt_default(stdscr, "SSH key path", conn.key_path)

    port, err = parse_port(port_raw)
    if err or port is None:
        return connections, err or "Invalid port."

    updated_conn = SSHConnection(
        name=sanitize_field(name) or host,
        host=sanitize_field(host),
        user=sanitize_field(user),
        port=port,
        key_path=sanitize_field(key_path),
    )

    updated = connections[:]
    updated[selected] = updated_conn
    save_connections(updated)
    return updated, f"Updated host: {updated_conn.summary()}"


def delete_connection_flow(stdscr: curses.window, connections: list[SSHConnection], selected: int) -> tuple[list[SSHConnection], int, str]:
    if not connections:
        return connections, selected, "No hosts to delete."

    conn = connections[selected]
    confirm = prompt_input(stdscr, f"Delete '{conn.name}'? Type YES to confirm: ")
    if confirm != "YES":
        return connections, selected, "Delete canceled."

    updated = [c for i, c in enumerate(connections) if i != selected]
    save_connections(updated)
    new_selected = max(0, min(selected, len(updated) - 1))
    return updated, new_selected, f"Deleted host: {conn.name}"


def app(stdscr: curses.window) -> None:
    root = stdscr
    stdscr = menu_bar.content_window(root)
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)

    root.keypad(True)
    stdscr.keypad(True)

    connections, warning = load_connections()
    selected = 0
    status = warning or "Ready"

    while True:
        if selected >= len(connections):
            selected = max(0, len(connections) - 1)

        draw_menu(stdscr, connections, selected, status)
        menu_bar.draw_menu_bar(root, APP_TITLE, False)
        root.refresh()
        key = stdscr.getch()

        if key in (ord("x"), ord("X")):
            return
        if key == curses.KEY_F1:
            choice = menu_bar.open_menu(root, APP_TITLE, ROOT_DIR, THIS_FILE)
            if choice == menu_bar.EXIT_ACTION:
                return
            if isinstance(choice, Path):
                menu_bar.switch_to_app(choice)
            continue
        if key == curses.KEY_UP and connections:
            selected = (selected - 1) % len(connections)
            continue
        if key == curses.KEY_DOWN and connections:
            selected = (selected + 1) % len(connections)
            continue

        if key in (ord("a"), ord("A")):
            connections, status = add_connection_flow(stdscr, connections)
            continue

        if key in (ord("q"), ord("Q")):
            connections, conn, status = quick_connect_flow(stdscr, connections)
            if conn:
                rc = run_ssh_session(stdscr, conn)
                status = f"Session ended for {conn.target()} (exit {rc})."
            continue

        if key in (ord("e"), ord("E")):
            connections, status = edit_connection_flow(stdscr, connections, selected)
            continue

        if key in (ord("d"), ord("D")):
            connections, selected, status = delete_connection_flow(stdscr, connections, selected)
            continue

        if key in (curses.KEY_ENTER, 10, 13):
            if not connections:
                status = "No saved hosts to connect. Add one with A."
                continue
            conn = connections[selected]
            rc = run_ssh_session(stdscr, conn)
            status = f"Session ended for {conn.target()} (exit {rc})."


def main() -> None:
    ok, msg = check_ssh_available()
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
