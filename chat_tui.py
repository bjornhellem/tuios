#!/usr/bin/env python3
"""Matrix-themed chat client for TuiOS."""

from __future__ import annotations

import curses
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import menu_bar
from chat_common import (
    CHAT_PORT,
    LOG_FILE,
    PEERS_FILE,
    append_log,
    load_peers,
    load_self_nickname,
    peer_name,
    read_log,
)

APP_TITLE = "Matrix Chat"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent


def truncate_text(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def format_timestamp(ts: str | None) -> str:
    if not ts:
        return "--:--"
    try:
        parsed = dt.datetime.fromisoformat(ts)
        return parsed.strftime("%H:%M")
    except Exception:
        return ts[:5]


def format_entry(entry: dict) -> str:
    timestamp = format_timestamp(entry.get("timestamp"))
    direction = entry.get("direction", "in")
    nickname = entry.get("nickname") or entry.get("ip", "unknown")
    message = entry.get("message", "")
    marker = "<" if direction == "in" else ">"
    return f"{timestamp} {marker} {nickname}: {message}"


def load_history_lines(target_ip: str | None) -> list[str]:
    entries = read_log()
    if target_ip:
        entries = [entry for entry in entries if entry.get("ip") == target_ip]
    else:
        entries = []
    return [format_entry(entry) for entry in entries]


def peers_summary(peers: dict[str, str], max_items: int = 4) -> str:
    items = []
    for ip, nickname in sorted(peers.items(), key=lambda item: item[1].lower()):
        label = nickname.strip() or ip
        items.append(f"{label}({ip})")
    if not items:
        return "Peers: none"
    if len(items) <= max_items:
        return f"Peers: {', '.join(items)}"
    remainder = len(items) - max_items
    preview = ", ".join(items[:max_items])
    return f"Peers: {preview}, +{remainder} more"

def prompt_input(stdscr: curses.window, label: str, restore_timeout: int) -> str:
    h, w = stdscr.getmaxyx()
    prompt = truncate_text(label, max(1, w - 2))
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h - 1, 1, " " * max(0, w - 2), max(0, w - 2))
    stdscr.addnstr(h - 1, 1, prompt, max(0, w - 2))
    stdscr.attroff(curses.color_pair(2))
    stdscr.refresh()

    stdscr.timeout(-1)
    curses.echo()
    curses.curs_set(1)
    start_x = min(w - 2, len(prompt) + 2)
    max_len = max(1, w - start_x - 1)
    raw = stdscr.getstr(h - 1, start_x, max_len)
    curses.noecho()
    curses.curs_set(0)
    stdscr.timeout(restore_timeout)
    return raw.decode("utf-8", errors="ignore").strip()


def post_message(target_ip: str, message: str) -> tuple[bool, str]:
    payload = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{target_ip}:{CHAT_PORT}/message",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except Exception as exc:
        return False, str(exc)
    return True, "Delivered"


def check_status(target_ip: str) -> str:
    req = urllib.request.Request(
        f"http://{target_ip}:{CHAT_PORT}/status",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return "Online"
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return "Blocked"
        return f"HTTP {exc.code}"
    except Exception:
        return "Offline"


def draw_ui(
    stdscr: curses.window,
    history_lines: list[str],
    target_ip: str,
    conn_status: str,
    message_mode: bool,
    status: str,
) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    mode_label = "Message" if message_mode else "Command"
    header = (
        f"Self: {load_self_nickname()} | Target: {target_ip or 'not set'} "
        f"| Conn: {conn_status} | Mode: {mode_label} "
        f"| Port: {CHAT_PORT} | Peers: {PEERS_FILE.name}"
    )
    stdscr.addnstr(0, 1, truncate_text(header, w - 2), max(0, w - 2), curses.color_pair(2))

    history_height = max(0, h - 3)
    visible = history_lines[-history_height:] if history_height else []
    for idx, line in enumerate(visible):
        y = 1 + idx
        if y >= h - 2:
            break
        stdscr.addnstr(y, 1, truncate_text(line, w - 2), max(0, w - 2), curses.color_pair(1))

    help_text = "Enter: command  /peer <ip>  /message  /done  /peers  /quit  /help  F1: menu"
    stdscr.addnstr(h - 2, 1, truncate_text(help_text, w - 2), max(0, w - 2), curses.color_pair(3))
    stdscr.addnstr(h - 1, 1, truncate_text(status, w - 2), max(0, w - 2), curses.color_pair(2))
    stdscr.refresh()


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
    stdscr.timeout(500)

    peers = load_peers()
    target_ip = ""
    for ip in peers:
        if ip != "127.0.0.1":
            target_ip = ip
            break

    status = "Use /peer <ip> to set target. /message to start chatting."
    conn_status = "No target"
    message_mode = False
    last_status_check = 0.0
    status_interval = 3.0
    history_lines = load_history_lines(None)
    last_mtime = LOG_FILE.stat().st_mtime if LOG_FILE.exists() else None

    while True:
        now = time.monotonic()
        if target_ip and now - last_status_check >= status_interval:
            conn_status = check_status(target_ip)
            last_status_check = now
        if not target_ip:
            conn_status = "No target"

        draw_ui(stdscr, history_lines, target_ip, conn_status, message_mode, status)
        menu_bar.draw_menu_bar(root, APP_TITLE, False)
        root.refresh()

        key = stdscr.getch()

        if key == -1:
            if LOG_FILE.exists():
                mtime = LOG_FILE.stat().st_mtime
                if mtime != last_mtime:
                    history_lines = load_history_lines(target_ip or None)
                    last_mtime = mtime
            continue

        if key in (ord("q"), ord("Q")):
            return

        if key == curses.KEY_F1:
            choice = menu_bar.open_menu(root, APP_TITLE, ROOT_DIR, THIS_FILE)
            if choice == menu_bar.EXIT_ACTION:
                return
            if isinstance(choice, Path):
                menu_bar.switch_to_app(choice)
            continue

        if key in (10, 13, curses.KEY_ENTER):
            if message_mode:
                if not target_ip:
                    status = "No target set. Use /peer <ip>."
                    continue
                message = prompt_input(stdscr, "Message: ", restore_timeout=500)
                if not message:
                    status = "Message canceled."
                    continue
                if message.startswith("/"):
                    # Allow commands even in message mode.
                    command = message
                else:
                    ok, detail = post_message(target_ip, message)
                    if ok:
                        nickname = load_self_nickname()
                        entry = {
                            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                            "direction": "out",
                            "ip": target_ip,
                            "nickname": nickname,
                            "message": message,
                        }
                        append_log(entry)
                        history_lines.append(format_entry(entry))
                        last_mtime = LOG_FILE.stat().st_mtime if LOG_FILE.exists() else None
                    status = detail if ok else f"Send failed: {detail}"
                    continue
            else:
                command = prompt_input(stdscr, "Command (/help): ", restore_timeout=500)

            if not command:
                status = "Command canceled."
                continue

            parts = command.strip().split()
            cmd = parts[0].lower()

            if cmd in ("/quit", "/exit"):
                return
            if cmd in ("/help", "/?"):
                status = "Commands: /peer <ip>, /message, /done, /peers, /quit"
                continue
            if cmd in ("/message", "/msg"):
                message_mode = True
                status = "Message mode on. Enter to send, /done to stop."
                continue
            if cmd in ("/done", "/stop"):
                message_mode = False
                status = "Message mode off. Enter commands with /help."
                continue
            if cmd in ("/peer", "/connect"):
                if len(parts) < 2:
                    status = "Usage: /peer <ip>"
                    continue
                target_ip = parts[1]
                status = f"Target set to {target_ip}."
                conn_status = "Checking..."
                last_status_check = 0.0
                history_lines = load_history_lines(target_ip)
                last_mtime = LOG_FILE.stat().st_mtime if LOG_FILE.exists() else None
                continue
            if cmd in ("/peers", "/list"):
                peers = load_peers()
                status = peers_summary(peers)
                continue

            status = f"Unknown command: {cmd}. Use /help."


if __name__ == "__main__":
    curses.wrapper(app)
