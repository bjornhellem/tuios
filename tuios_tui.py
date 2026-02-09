#!/usr/bin/env python3
"""TuiOS: Matrix-themed desktop-like launcher for local TUI scripts."""

from __future__ import annotations

import curses
import datetime as dt
import getpass
import math
import platform
import shutil
import socket
import subprocess
import sys
import time
import wave
from pathlib import Path
from tempfile import NamedTemporaryFile

from chat_common import load_peers
from chat_server import ChatServer

APP_NAME = "TuiOS"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent
MENU_TITLE = "Apps"
PLAY_STARTUP_SOUND = True

SPLASH_ART = [
    "  _______        _ ____   _____ ",
    " |__   __|      (_)  _ \\ / ____|",
    "    | |_   _ ___ _| |_) | (___  ",
    "    | | | | / __| |  _ < \\___ \\ ",
    "    | | |_| \\__ \\ | |_) |____) |",
    "    |_|\\__,_|___/_|____/|_____/ ",
]

LANDSCAPE_ART = [
    "               _      _                     ",
    "            .-''-.  .-''-.                  ",
    "         .-'_    \\/    _'-.                 ",
    "        /   /\\        /\\   \\        _       ",
    "       /   /  \\  /\\  /  \\   \\    .-' '-.    ",
    "      /___/____\\/__\\/____\\___\\  /  .-.  \\   ",
    "      |  _   _   _   _   _  |  |  | |  |   ",
    "      | |_| |_| |_| |_| |_| |  |  |_|  |   ",
    "  ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ \\     / ~  ",
    " ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ '-.-' ~ ~ ",
]


def scan_tui_scripts() -> list[Path]:
    scripts = []
    for path in sorted(ROOT_DIR.glob("*.py"), key=lambda p: p.name.lower()):
        if path.resolve() == THIS_FILE:
            continue
        if "tui" in path.stem.lower():
            scripts.append(path)
    return scripts


def get_uptime_text() -> str:
    try:
        proc = subprocess.run(["uptime"], capture_output=True, text=True, check=False, timeout=2)
    except Exception:
        return "n/a"
    if proc.returncode != 0:
        return "n/a"
    return (proc.stdout or "").strip() or "n/a"


def get_system_info() -> list[str]:
    disk = shutil.disk_usage(ROOT_DIR)
    free_gb = disk.free / (1024**3)
    total_gb = disk.total / (1024**3)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    peers = load_peers()
    peer_label = format_peer_summary(peers)
    return [
        f"Time: {now}",
        f"Host: {socket.gethostname()}",
        f"User: {getpass.getuser()}",
        f"Python: {platform.python_version()}",
        f"Platform: {platform.system()} {platform.release()}",
        f"Disk: {free_gb:.1f} GB free / {total_gb:.1f} GB",
        f"Uptime: {get_uptime_text()}",
        peer_label,
    ]


def center_x(width: int, text: str) -> int:
    return max(0, (width - len(text)) // 2)


def format_peer_summary(peers: dict[str, str], max_items: int = 3) -> str:
    names = [value.strip() for value in peers.values() if value.strip()]
    labels = sorted(set(names))
    if not labels:
        return "Chat peers: 0"
    if len(labels) <= max_items:
        return f"Chat peers: {len(labels)} ({', '.join(labels)})"
    remainder = len(labels) - max_items
    preview = ", ".join(labels[:max_items])
    return f"Chat peers: {len(labels)} ({preview}, +{remainder} more)"

def generate_startup_wav(path: Path) -> None:
    sample_rate = 22050
    volume = 0.4
    notes = [
        (523.25, 0.12),  # C5
        (659.25, 0.12),  # E5
        (783.99, 0.16),  # G5
        (1046.50, 0.22), # C6
        (987.77, 0.10),  # B5
        (1046.50, 0.18), # C6
        (1318.51, 0.16), # E6
        (1046.50, 0.24), # C6 (resolve)
    ]
    silence = 0.04

    frames: list[int] = []
    for freq, duration in notes:
        total = int(sample_rate * duration)
        for i in range(total):
            t = i / sample_rate
            wave_val = 1 if math.sin(2 * math.pi * freq * t) >= 0 else -1
            sample = int((wave_val * volume + 1) * 127.5)
            frames.append(sample)
        gap = int(sample_rate * silence)
        frames.extend([128] * gap)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def play_startup_sound() -> tuple[subprocess.Popen | None, Path | None]:
    if not PLAY_STARTUP_SOUND:
        return None, None
    if shutil.which("afplay") is None:
        return None, None
    temp = NamedTemporaryFile(prefix="tuios_startup_", suffix=".wav", delete=False)
    temp_path = Path(temp.name)
    temp.close()
    try:
        generate_startup_wav(temp_path)
        proc = subprocess.Popen(
            ["afplay", str(temp_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc, temp_path
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        return None, None


def cleanup_sound(proc: subprocess.Popen | None, temp_path: Path | None) -> None:
    if proc is not None:
        try:
            proc.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
    if temp_path is not None:
        try:
            temp_path.unlink()
        except OSError:
            pass


def draw_splash(stdscr: curses.window) -> None:
    proc, temp_path = play_startup_sound()
    start = time.time()
    duration = 3.0
    username = getpass.getuser()
    while time.time() - start < duration:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        y = max(1, h // 2 - len(SPLASH_ART) // 2 - 1)

        for idx, line in enumerate(SPLASH_ART):
            stdscr.addnstr(y + idx, center_x(w, line), line, w - 1, curses.color_pair(3))

        status = f"Welcome {username}! Booting TuiOS..."
        stdscr.addnstr(y + len(SPLASH_ART) + 2, center_x(w, status), status, w - 1, curses.color_pair(2))
        stdscr.refresh()
        time.sleep(0.06)
    cleanup_sound(proc, temp_path)


def draw_menu_bar(stdscr: curses.window, menu_open: bool) -> None:
    _, w = stdscr.getmaxyx()
    stdscr.addnstr(0, 0, " " * max(0, w - 1), w - 1, curses.color_pair(3))
    stdscr.addnstr(0, 1, f"{APP_NAME}", w - 2, curses.color_pair(3))

    label = f"[{MENU_TITLE}]" if menu_open else MENU_TITLE
    stdscr.addnstr(0, 12, label, max(0, w - 13), curses.color_pair(3))

    clock = dt.datetime.now().strftime("%H:%M:%S")
    right_x = max(1, w - len(clock) - 2)
    stdscr.addnstr(0, right_x, clock, len(clock), curses.color_pair(3))


def draw_dropdown(stdscr: curses.window, entries: list[str], selected: int) -> None:
    h, w = stdscr.getmaxyx()
    max_label = max((len(e) for e in entries), default=10)
    box_w = min(w - 4, max(20, max_label + 4))
    box_h = min(h - 3, len(entries) + 2)
    x = 12
    y = 1

    for i in range(box_h):
        stdscr.addnstr(y + i, x, " " * box_w, box_w, curses.color_pair(1))

    stdscr.addnstr(y, x + 1, f" {MENU_TITLE} ", box_w - 2, curses.color_pair(3))
    visible = entries[: max(0, box_h - 2)]
    for idx, label in enumerate(visible):
        color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
        marker = ">" if idx == selected else " "
        stdscr.addnstr(y + idx + 1, x + 1, f"{marker} {label}", box_w - 2, color)


def draw_desktop(stdscr: curses.window, menu_open: bool, menu_entries: list[str], selected: int, status: str) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_menu_bar(stdscr, menu_open)

    # Draw landscape near the lower-middle area.
    base_y = max(2, h // 2 - len(LANDSCAPE_ART) // 2 + 2)
    for row, line in enumerate(LANDSCAPE_ART):
        y = base_y + row
        if y >= h - 2:
            break
        stdscr.addnstr(y, center_x(w, line), line, w - 1, curses.color_pair(2))

    info_lines = get_system_info()
    info_x = 2
    info_y = 2
    stdscr.addnstr(info_y, info_x, "System Info", w - 4, curses.color_pair(3))
    for idx, line in enumerate(info_lines):
        y = info_y + 1 + idx
        if y >= h - 2:
            break
        stdscr.addnstr(y, info_x, line, w - 4, curses.color_pair(2))

    footer = "M: menu  R: refresh apps  ENTER: open app  Q: quit"
    stdscr.addnstr(h - 2, 1, status[: max(0, w - 2)], max(0, w - 2), curses.color_pair(2))
    stdscr.addnstr(h - 1, 1, footer[: max(0, w - 2)], max(0, w - 2), curses.color_pair(3))

    if menu_open:
        draw_dropdown(stdscr, menu_entries, selected)

    stdscr.refresh()


def launch_app(stdscr: curses.window, app_path: Path) -> str:
    curses.def_prog_mode()
    curses.endwin()
    try:
        print(f"\n[TuiOS] Launching {app_path.name} ...\n")
        proc = subprocess.run([sys.executable, str(app_path)], check=False)
        input("\n[TuiOS] Press Enter to return to desktop...")
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.clear()
        stdscr.refresh()
    return f"Exited {app_path.name} with code {proc.returncode}"


def to_menu_entries(apps: list[Path]) -> list[str]:
    labels = [app.name for app in apps]
    labels.append("Refresh app list")
    labels.append("Exit TuiOS")
    return labels


def main(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)
    stdscr.keypad(True)
    stdscr.timeout(200)

    chat_server = ChatServer()
    _, server_msg = chat_server.start()

    draw_splash(stdscr)

    apps = scan_tui_scripts()
    menu_open = False
    selected = 0
    username = getpass.getuser()
    status = f"Welcome {username}! Found {len(apps)} TUI script(s). {server_msg}"

    try:
        while True:
            menu_entries = to_menu_entries(apps)
            selected = max(0, min(selected, len(menu_entries) - 1))
            draw_desktop(stdscr, menu_open, menu_entries, selected, status)
            key = stdscr.getch()

            if key == -1:
                continue

            if key in (ord("q"), ord("Q")):
                break

            if key in (ord("r"), ord("R")):
                apps = scan_tui_scripts()
                selected = 0
                status = f"App list refreshed. Found {len(apps)} TUI script(s)."
                continue

            if key in (ord("m"), ord("M")):
                menu_open = not menu_open
                continue

            if not menu_open and key in (10, 13, curses.KEY_ENTER):
                menu_open = True
                continue

            if not menu_open:
                continue

            if key in (27,):  # ESC
                menu_open = False
                continue
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(menu_entries)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(menu_entries)
                continue
            if key in (10, 13, curses.KEY_ENTER):
                choice = menu_entries[selected]
                if choice == "Refresh app list":
                    apps = scan_tui_scripts()
                    selected = 0
                    status = f"App list refreshed. Found {len(apps)} TUI script(s)."
                elif choice == "Exit TuiOS":
                    break
                else:
                    app_path = ROOT_DIR / choice
                    if app_path.exists():
                        status = launch_app(stdscr, app_path)
                    else:
                        status = f"File not found: {choice}"
                    menu_open = False
    finally:
        chat_server.stop()


if __name__ == "__main__":
    curses.wrapper(main)
