#!/usr/bin/env python3
"""Matrix-themed file manager TUI for macOS/Linux terminals."""

from __future__ import annotations

import curses
import os
import shutil
import stat
import subprocess
from pathlib import Path

import menu_bar

APP_TITLE = "Matrix File Manager"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent


def draw_global_menu() -> None:
    root = menu_bar.root_window()
    if root is None:
        return
    menu_bar.draw_menu_bar(root, APP_TITLE, False)
    root.refresh()
MAX_TREE_DEPTH = 3
MAX_TREE_NODES = 250


def truncate_text(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def list_body_height(screen_height: int) -> int:
    # One row is used for items column headers.
    return max(1, screen_height - 8)


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


def prompt_secret(stdscr: curses.window, label: str) -> str:
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h - 3, 2, " " * (w - 4), w - 4)
    stdscr.addnstr(h - 3, 2, label[: w - 6], w - 6)
    stdscr.attroff(curses.color_pair(2))

    curses.noecho()
    curses.curs_set(1)
    buf: list[str] = []

    while True:
        stdscr.addnstr(h - 2, 2, " " * (w - 4), w - 4)
        stdscr.addnstr(h - 2, 2, "*" * len(buf), w - 4)
        stdscr.refresh()
        key = stdscr.getch()
        if key in (10, 13, curses.KEY_ENTER):
            break
        if key in (27,):  # ESC
            buf = []
            break
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
            continue
        if 32 <= key <= 126:
            buf.append(chr(key))

    curses.curs_set(0)
    return "".join(buf)


def run_sudo(password: str, args: list[str]) -> tuple[bool, str]:
    if not password:
        return False, "Sudo canceled (empty password)."
    proc = subprocess.run(
        ["sudo", "-S", "-p", "", *args],
        input=password + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "Unknown sudo error"
    return False, err


def perms_string(path: Path) -> str:
    try:
        mode = path.stat().st_mode
        return stat.filemode(mode)
    except OSError:
        return "??????????"


def list_dir(path: Path) -> tuple[list[Path], str | None]:
    try:
        items = [Path(entry.path) for entry in os.scandir(path)]
    except OSError as exc:
        return [], str(exc)

    items.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    return items, None


def is_plain_text(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            sample = f.read(4096)
    except OSError:
        return False

    if b"\x00" in sample:
        return False

    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def read_text_lines(path: Path) -> tuple[list[str], str | None]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines(), None
    except OSError as exc:
        return [], str(exc)


def build_tree_lines(root: Path) -> list[str]:
    lines: list[str] = [str(root)]
    nodes = 1

    def walk(base: Path, prefix: str, depth: int) -> None:
        nonlocal nodes
        if depth >= MAX_TREE_DEPTH or nodes >= MAX_TREE_NODES:
            return

        try:
            dirs = sorted(
                [Path(entry.path) for entry in os.scandir(base) if entry.is_dir(follow_symlinks=False)],
                key=lambda p: p.name.lower(),
            )
        except OSError:
            lines.append(prefix + "[permission denied]")
            return

        for idx, child in enumerate(dirs):
            if nodes >= MAX_TREE_NODES:
                lines.append(prefix + "...")
                return
            connector = "`-- " if idx == len(dirs) - 1 else "|-- "
            lines.append(prefix + connector + child.name)
            nodes += 1
            walk(child, prefix + ("    " if idx == len(dirs) - 1 else "|   "), depth + 1)

    walk(root, "", 0)
    return lines


def copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def paste_with_fallback(stdscr: curses.window, source: Path, dest_dir: Path, mode: str) -> tuple[bool, str]:
    destination = dest_dir / source.name
    if destination.exists():
        return False, f"Destination exists: {destination}"

    try:
        if mode == "copy":
            copy_path(source, destination)
        else:
            shutil.move(str(source), str(destination))
        return True, f"{mode.title()} OK: {source.name}"
    except PermissionError:
        password = prompt_secret(stdscr, "Permission denied. Sudo password (ESC cancels): ")
        if not password:
            return False, "Operation canceled."
        command = ["cp", "-a", str(source), str(destination)] if mode == "copy" else ["mv", str(source), str(destination)]
        ok, err = run_sudo(password, command)
        if ok:
            return True, f"{mode.title()} with sudo OK: {source.name}"
        return False, f"Sudo {mode} failed: {err}"
    except OSError as exc:
        return False, f"{mode.title()} failed: {exc}"


def chmod_with_fallback(stdscr: curses.window, target: Path, mode_str: str) -> tuple[bool, str]:
    try:
        mode = int(mode_str, 8)
    except ValueError:
        return False, "Mode must be octal (example: 755 or 644)."

    try:
        os.chmod(target, mode)
        return True, f"Permissions updated: {target.name} -> {mode_str}"
    except PermissionError:
        password = prompt_secret(stdscr, "Permission denied. Sudo password (ESC cancels): ")
        if not password:
            return False, "Operation canceled."
        ok, err = run_sudo(password, ["chmod", mode_str, str(target)])
        if ok:
            return True, f"Permissions updated with sudo: {target.name} -> {mode_str}"
        return False, f"Sudo chmod failed: {err}"
    except OSError as exc:
        return False, f"chmod failed: {exc}"


def move_to_path(stdscr: curses.window, source: Path, destination: Path) -> tuple[bool, str]:
    if destination.exists():
        return False, f"Destination exists: {destination}"

    try:
        shutil.move(str(source), str(destination))
        return True, f"Moved: {source.name} -> {destination}"
    except PermissionError:
        password = prompt_secret(stdscr, "Permission denied. Sudo password (ESC cancels): ")
        if not password:
            return False, "Operation canceled."
        ok, err = run_sudo(password, ["mv", str(source), str(destination)])
        if ok:
            return True, f"Moved with sudo: {source.name}"
        return False, f"Sudo move failed: {err}"
    except OSError as exc:
        return False, f"Move failed: {exc}"


def view_text_file(stdscr: curses.window, path: Path) -> None:
    lines, err = read_text_lines(path)
    if err:
        show_message(stdscr, "View File", f"Failed to read file: {err}")
        return

    offset = 0
    while True:
        draw_boxed(stdscr, f"View: {path.name}")
        h, w = stdscr.getmaxyx()
        body_h = h - 4
        visible = lines[offset : offset + body_h]

        for i, line in enumerate(visible, start=1):
            stdscr.addnstr(i, 2, line, w - 4, curses.color_pair(2))

        footer = "UP/DOWN scroll  PGUP/PGDN page  B back"
        stdscr.addnstr(h - 2, 2, footer, w - 4, curses.color_pair(3))
        stdscr.refresh()
        draw_global_menu()

        key = stdscr.getch()
        if key in (ord("b"), ord("B"), 27):
            return
        if key == curses.KEY_F1:
            choice = menu_bar.open_menu(menu_bar.root_window(), APP_TITLE, ROOT_DIR, THIS_FILE)
            if choice == menu_bar.EXIT_ACTION:
                return
            if isinstance(choice, Path):
                menu_bar.switch_to_app(choice)
            continue
        if key == curses.KEY_UP and offset > 0:
            offset -= 1
        elif key == curses.KEY_DOWN and offset + body_h < len(lines):
            offset += 1
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - body_h)
        elif key == curses.KEY_NPAGE:
            offset = min(max(0, len(lines) - body_h), offset + body_h)


def show_message(stdscr: curses.window, title: str, message: str) -> None:
    draw_boxed(stdscr, title)
    h, w = stdscr.getmaxyx()
    stdscr.addnstr(2, 2, message, w - 4, curses.color_pair(2))
    stdscr.addnstr(4, 2, "Press any key...", w - 4, curses.color_pair(3))
    stdscr.refresh()
    draw_global_menu()
    key = stdscr.getch()
    if key == curses.KEY_F1:
        choice = menu_bar.open_menu(menu_bar.root_window(), APP_TITLE, ROOT_DIR, THIS_FILE)
        if choice == menu_bar.EXIT_ACTION:
            return
        if isinstance(choice, Path):
            menu_bar.switch_to_app(choice)


def draw_ui(
    stdscr: curses.window,
    cwd: Path,
    entries: list[Path],
    selected: int,
    list_offset: int,
    status: str,
    clipboard: Path | None,
    clipboard_mode: str | None,
) -> None:
    draw_boxed(stdscr, "Matrix File Manager")
    h, w = stdscr.getmaxyx()

    tree_w = max(28, min(42, w // 3))
    sep_x = tree_w + 1
    body_h = list_body_height(h)

    stdscr.vline(1, sep_x, curses.ACS_VLINE, h - 3)
    stdscr.addnstr(1, 2, "Folder tree", tree_w - 1, curses.color_pair(3))
    stdscr.addnstr(1, sep_x + 2, "Items", w - sep_x - 4, curses.color_pair(3))
    stdscr.addnstr(2, sep_x + 2, "TYPE NAME PERMISSIONS", w - sep_x - 4, curses.color_pair(3))

    tree_lines = build_tree_lines(cwd)
    for i, line in enumerate(tree_lines[: body_h + 1]):
        stdscr.addnstr(2 + i, 2, line, tree_w - 1, curses.color_pair(2))

    visible = entries[list_offset : list_offset + body_h]
    row_start = 3
    items_w = max(10, w - sep_x - 4)
    marker_w = 2
    type_w = 3
    perms_w = 10
    min_name_w = 6

    fixed = marker_w + type_w + perms_w + 4  # spaces between columns
    if items_w - fixed < min_name_w:
        # On tiny terminals, keep name readable and trim permissions first.
        perms_w = max(4, items_w - (marker_w + type_w + min_name_w + 4))
    name_w = max(1, items_w - (marker_w + type_w + perms_w + 4))

    for i, entry in enumerate(visible):
        idx = list_offset + i
        y = row_start + i
        marker = ">" if idx == selected else " "
        color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
        typ = "[D]" if entry.is_dir() else "[F]"
        name = truncate_text(entry.name, name_w)
        perms = truncate_text(perms_string(entry), perms_w)
        line = f"{marker:<{marker_w}} {typ:<{type_w}} {name:<{name_w}} {perms:>{perms_w}}"
        stdscr.addnstr(y, sep_x + 2, line, items_w, color)

    clip = f"{clipboard_mode}:{clipboard.name}" if clipboard and clipboard_mode else "empty"
    stdscr.addnstr(h - 5, 2, f"Status: {status}", w - 4, curses.color_pair(2))
    stdscr.addnstr(h - 4, 2, f"Current: {cwd}", w - 4, curses.color_pair(2))
    stdscr.addnstr(h - 3, 2, f"Clipboard: {clip}", w - 4, curses.color_pair(2))
    stdscr.addnstr(
        h - 2,
        2,
        "ENTER open/view  BACKSPACE up  C copy  X cut  P paste  M move-to  H chmod  Q quit",
        w - 4,
        curses.color_pair(3),
    )
    stdscr.refresh()


def app(stdscr: curses.window) -> None:
    root = stdscr
    stdscr = menu_bar.content_window(root)
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Same matrix palette as nmap_tui.py
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)

    root.keypad(True)
    stdscr.keypad(True)

    cwd = Path.cwd()
    entries: list[Path] = []
    selected = 0
    list_offset = 0
    status = "Ready"
    clipboard: Path | None = None
    clipboard_mode: str | None = None

    while True:
        entries, err = list_dir(cwd)
        if err:
            status = f"Failed to list {cwd}: {err}"
            entries = []

        if selected >= len(entries):
            selected = max(0, len(entries) - 1)
        h, _w = stdscr.getmaxyx()
        body_h = list_body_height(h)
        if selected < list_offset:
            list_offset = selected
        elif selected >= list_offset + body_h:
            list_offset = selected - body_h + 1

        draw_ui(stdscr, cwd, entries, selected, list_offset, status, clipboard, clipboard_mode)
        menu_bar.draw_menu_bar(root, APP_TITLE, False)
        root.refresh()
        key = stdscr.getch()

        if key in (ord("q"), ord("Q")):
            return
        if key == curses.KEY_F1:
            choice = menu_bar.open_menu(root, APP_TITLE, ROOT_DIR, THIS_FILE)
            if choice == menu_bar.EXIT_ACTION:
                return
            if isinstance(choice, Path):
                menu_bar.switch_to_app(choice)
            continue
        if key == curses.KEY_UP and selected > 0:
            selected -= 1
            status = ""
        elif key == curses.KEY_DOWN and selected < len(entries) - 1:
            selected += 1
            status = ""
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            parent = cwd.parent
            if parent != cwd:
                cwd = parent
                selected = 0
                list_offset = 0
                status = f"Moved to: {cwd}"
        elif key in (10, 13, curses.KEY_ENTER):
            if not entries:
                continue
            target = entries[selected]
            if target.is_dir():
                cwd = target
                selected = 0
                list_offset = 0
                status = f"Entered: {target.name}"
            elif is_plain_text(target):
                view_text_file(stdscr, target)
                status = f"Viewed: {target.name}"
            else:
                status = "Only plain text files are viewable."
        elif key in (ord("c"), ord("C")):
            if not entries:
                continue
            clipboard = entries[selected]
            clipboard_mode = "copy"
            status = f"Copied to clipboard: {clipboard.name}"
        elif key in (ord("x"), ord("X")):
            if not entries:
                continue
            clipboard = entries[selected]
            clipboard_mode = "move"
            status = f"Cut to clipboard: {clipboard.name}"
        elif key in (ord("p"), ord("P")):
            if not clipboard or not clipboard_mode:
                status = "Clipboard is empty."
                continue
            if not clipboard.exists():
                status = "Clipboard source no longer exists."
                clipboard = None
                clipboard_mode = None
                continue

            ok, msg = paste_with_fallback(stdscr, clipboard, cwd, clipboard_mode)
            status = msg
            if ok and clipboard_mode == "move":
                clipboard = None
                clipboard_mode = None
        elif key in (ord("h"), ord("H")):
            if not entries:
                continue
            target = entries[selected]
            mode_str = prompt_input(stdscr, f"chmod mode for {target.name} (example 755): ")
            if not mode_str:
                status = "chmod canceled."
                continue
            ok, msg = chmod_with_fallback(stdscr, target, mode_str)
            status = msg
        elif key in (ord("m"), ord("M")):
            if not entries:
                continue
            source = entries[selected]
            raw_dest = prompt_input(stdscr, "Move selected item to destination path: ")
            if not raw_dest:
                status = "Move canceled."
                continue
            destination = Path(raw_dest).expanduser()
            if not destination.is_absolute():
                destination = cwd / destination
            ok, msg = move_to_path(stdscr, source, destination)
            status = msg


def main() -> None:
    try:
        curses.wrapper(app)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except curses.error:
        print("Terminal too small or unsupported for curses UI.")


if __name__ == "__main__":
    main()
