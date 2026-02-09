#!/usr/bin/env python3
"""Shared menubar and app switcher for TuiOS apps."""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Iterable

import curses

APP_NAME = "TuiOS"
MENU_TITLE = "Apps"
EXIT_ACTION = "__EXIT__"
_ROOT_WINDOW: curses.window | None = None


def content_window(stdscr: curses.window) -> curses.window:
    h, w = stdscr.getmaxyx()
    global _ROOT_WINDOW
    _ROOT_WINDOW = stdscr
    return curses.newwin(max(1, h - 1), w, 1, 0)


def root_window() -> curses.window | None:
    return _ROOT_WINDOW


def scan_tui_apps(root_dir: Path, current_path: Path | None = None) -> list[Path]:
    apps = []
    for path in sorted(root_dir.glob("*.py"), key=lambda p: p.name.lower()):
        if current_path and path.resolve() == current_path.resolve():
            apps.append(path)
            continue
        if "tui" in path.stem.lower():
            apps.append(path)
    if current_path and current_path not in apps:
        apps.append(current_path)
    return apps


def draw_menu_bar(stdscr: curses.window, app_title: str, menu_open: bool) -> None:
    _, w = stdscr.getmaxyx()
    stdscr.addnstr(0, 0, " " * max(0, w - 1), w - 1, curses.color_pair(3))
    stdscr.addnstr(0, 1, APP_NAME, w - 2, curses.color_pair(3))

    label = f"[{MENU_TITLE}]" if menu_open else MENU_TITLE
    stdscr.addnstr(0, 12, label, max(0, w - 13), curses.color_pair(3))

    clock = dt.datetime.now().strftime("%H:%M:%S")
    title = f"{app_title}"
    center_x = max(1, (w - len(title)) // 2)
    stdscr.addnstr(0, center_x, title, max(0, w - center_x - 1), curses.color_pair(3))

    right_x = max(1, w - len(clock) - 2)
    stdscr.addnstr(0, right_x, clock, len(clock), curses.color_pair(3))


def _draw_dropdown(
    stdscr: curses.window, entries: Iterable[str], selected: int
) -> tuple[int, int, int, int]:
    h, w = stdscr.getmaxyx()
    entry_list = list(entries)
    max_label = max((len(e) for e in entry_list), default=10)
    box_w = min(w - 4, max(24, max_label + 4))
    box_h = min(h - 3, len(entry_list) + 2)
    x = 12
    y = 1

    for i in range(box_h):
        stdscr.addnstr(y + i, x, " " * box_w, box_w, curses.color_pair(1))

    stdscr.addnstr(y, x + 1, f" {MENU_TITLE} ", box_w - 2, curses.color_pair(3))
    visible = entry_list[: max(0, box_h - 2)]
    for idx, label in enumerate(visible):
        color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
        marker = ">" if idx == selected else " "
        stdscr.addnstr(y + idx + 1, x + 1, f"{marker} {label}", box_w - 2, color)

    return x, y, box_w, box_h


def open_menu(
    stdscr: curses.window | None,
    app_title: str,
    root_dir: Path,
    current_path: Path | None,
) -> str | Path | None:
    if stdscr is None:
        stdscr = _ROOT_WINDOW
    if stdscr is None:
        return None
    apps = scan_tui_apps(root_dir, current_path)
    labels = [path.name for path in apps]
    labels.append("Exit app")
    selected = 0

    stdscr.nodelay(False)
    while True:
        draw_menu_bar(stdscr, app_title, True)
        _draw_dropdown(stdscr, labels, selected)
        stdscr.refresh()
        key = stdscr.getch()

        if key in (27,):  # ESC
            return None
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(labels)
            continue
        if key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(labels)
            continue
        if key in (10, 13, curses.KEY_ENTER):
            choice = labels[selected]
            if choice == "Exit app":
                return EXIT_ACTION
            for path in apps:
                if path.name == choice:
                    return path
        if key in (ord("q"), ord("Q")):
            return EXIT_ACTION


def switch_to_app(app_path: Path) -> None:
    os.execv(sys.executable, [sys.executable, str(app_path)])
