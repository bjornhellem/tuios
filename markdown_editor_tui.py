#!/usr/bin/env python3
"""MarkdownMatrix: a Matrix-themed split-view Markdown editor for the terminal."""

from __future__ import annotations

import curses
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


HELP_TEXT = "F2 save  F3 open  F4 new  F10 quit  F6 switch pane"


@dataclass
class EditorState:
    lines: list[str] = field(default_factory=lambda: [""])
    file_path: Path | None = None
    cursor_y: int = 0
    cursor_x: int = 0
    preferred_x: int = 0
    left_scroll_y: int = 0
    left_scroll_x: int = 0
    preview_scroll_y: int = 0
    focus: str = "left"  # left=editor, right=preview
    dirty: bool = False
    status: str = "Ready"

    def file_label(self) -> str:
        if self.file_path is None:
            return "[New File]"
        return str(self.file_path)


def prompt_input(stdscr: curses.window, label: str, initial: str = "") -> str:
    h, w = stdscr.getmaxyx()
    row_label = h - 3
    row_input = h - 2

    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(row_label, 2, " " * max(0, w - 4), max(0, w - 4))
    stdscr.addnstr(row_label, 2, label[: max(0, w - 4)], max(0, w - 4))
    stdscr.addnstr(row_input, 2, " " * max(0, w - 4), max(0, w - 4))
    stdscr.attroff(curses.color_pair(2))

    curses.echo()
    curses.curs_set(1)
    stdscr.move(row_input, 2)
    if initial:
        stdscr.addnstr(row_input, 2, initial[: max(0, w - 4)], max(0, w - 4))
        stdscr.move(row_input, 2 + min(len(initial), max(0, w - 4)))
    raw = stdscr.getstr(row_input, 2, max(1, w - 4))
    curses.noecho()
    curses.curs_set(0)
    return raw.decode("utf-8", errors="ignore").strip()


def confirm(stdscr: curses.window, message: str) -> bool:
    h, w = stdscr.getmaxyx()
    prompt = f"{message} [y/N]"
    stdscr.attron(curses.color_pair(2))
    stdscr.addnstr(h - 2, 2, " " * max(0, w - 4), max(0, w - 4))
    stdscr.addnstr(h - 2, 2, prompt[: max(0, w - 4)], max(0, w - 4))
    stdscr.attroff(curses.color_pair(2))
    stdscr.refresh()
    key = stdscr.getch()
    return key in (ord("y"), ord("Y"))


def load_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if text.endswith("\n"):
        lines.append("")
    return lines or [""]


def save_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def unwrap_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[image: \1]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    return text


def format_inline_preview(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[image: \1]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 <\2>", text)
    text = re.sub(r"`([^`]+)`", r"<C>\1</C>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<B>\1</B>", text)
    text = re.sub(r"__([^_]+)__", r"<B>\1</B>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<I>\1</I>", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<I>\1</I>", text)
    text = re.sub(r"~~([^~]+)~~", r"<S>\1</S>", text)
    return text


def wrap_line(text: str, width: int, preserve_spaces: bool = False) -> list[str]:
    if width <= 1:
        return [text[:1] if text else ""]
    if not text:
        return [""]
    if preserve_spaces:
        out: list[str] = []
        idx = 0
        while idx < len(text):
            out.append(text[idx : idx + width])
            idx += width
        return out or [""]
    return textwrap.wrap(text, width=width, replace_whitespace=False, drop_whitespace=False) or [""]


def detect_line_gutter(line: str) -> str:
    stripped = line.lstrip()
    if not stripped:
        return ""
    heading = re.match(r"^(#{1,6})\s+", stripped)
    if heading:
        return f"<H{len(heading.group(1))}>"
    return ""


def render_preview(lines: list[str], width: int) -> list[tuple[str, str]]:
    width = max(10, width)
    out: list[tuple[str, str]] = []
    in_code = False
    code_fence = ""

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        gutter = detect_line_gutter(line)

        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_code:
                in_code = True
                code_fence = stripped[:3]
                label = stripped[3:].strip()
                header = f"[code block: {label}]" if label else "[code block]"
                wrapped = wrap_line(header, width)
                for idx, chunk in enumerate(wrapped):
                    out.append((gutter if idx == 0 else "", chunk))
            elif stripped.startswith(code_fence):
                in_code = False
                out.append((gutter, "[end code block]"))
            continue

        if in_code:
            for chunk in wrap_line(f"  {line}", width, preserve_spaces=True):
                out.append(("", chunk))
            continue

        if not stripped:
            out.append(("", ""))
            continue

        if re.fullmatch(r"[-*_]{3,}", stripped.replace(" ", "")):
            out.append((gutter, "-" * width))
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            content = format_inline_preview(heading.group(2)).strip()
            prefix = "#" * level
            wrapped = wrap_line(f"{prefix} {content}", width)
            for idx, chunk in enumerate(wrapped):
                out.append((gutter if idx == 0 else "", chunk))
            out.append(("", "-"))
            continue

        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            content = format_inline_preview(quote.group(1))
            wrapped = wrap_line(f"| {content}", width)
            for idx, chunk in enumerate(wrapped):
                out.append((gutter if idx == 0 else "", chunk))
            continue

        ordered = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if ordered:
            indent = " " * min(len(ordered.group(1)), 12)
            marker = ordered.group(2)
            content = format_inline_preview(ordered.group(3))
            wrapped = wrap_line(f"{indent}{marker}. {content}", width)
            for idx, chunk in enumerate(wrapped):
                out.append((gutter if idx == 0 else "", chunk))
            continue

        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if bullet:
            indent = " " * min(len(bullet.group(1)), 12)
            content = format_inline_preview(bullet.group(2))
            wrapped = wrap_line(f"{indent}- {content}", width)
            for idx, chunk in enumerate(wrapped):
                out.append((gutter if idx == 0 else "", chunk))
            continue

        if "|" in line and line.count("|") >= 2:
            cells = [format_inline_preview(cell.strip()) for cell in line.strip("|").split("|")]
            row = " | ".join(cells)
            wrapped = wrap_line(row, width)
            for idx, chunk in enumerate(wrapped):
                out.append((gutter if idx == 0 else "", chunk))
            continue

        wrapped = wrap_line(format_inline_preview(line), width)
        for idx, chunk in enumerate(wrapped):
            out.append((gutter if idx == 0 else "", chunk))

    return out or [("", "")]


def keep_cursor_in_bounds(state: EditorState) -> None:
    state.cursor_y = max(0, min(state.cursor_y, len(state.lines) - 1))
    state.cursor_x = max(0, min(state.cursor_x, len(state.lines[state.cursor_y])))


def ensure_cursor_visible(state: EditorState, body_h: int, editor_w: int) -> None:
    if state.cursor_y < state.left_scroll_y:
        state.left_scroll_y = state.cursor_y
    elif state.cursor_y >= state.left_scroll_y + body_h:
        state.left_scroll_y = state.cursor_y - body_h + 1

    if state.cursor_x < state.left_scroll_x:
        state.left_scroll_x = state.cursor_x
    elif state.cursor_x >= state.left_scroll_x + editor_w:
        state.left_scroll_x = state.cursor_x - editor_w + 1

    state.left_scroll_y = max(0, state.left_scroll_y)
    state.left_scroll_x = max(0, state.left_scroll_x)


def set_status(state: EditorState, message: str) -> None:
    state.status = message


def open_flow(stdscr: curses.window, state: EditorState) -> None:
    if state.dirty and not confirm(stdscr, "Unsaved changes. Open anyway?"):
        set_status(state, "Open canceled.")
        return

    path_raw = prompt_input(stdscr, "Open .md file path: ")
    if not path_raw:
        set_status(state, "Open canceled.")
        return

    path = Path(path_raw).expanduser()
    if path.suffix.lower() != ".md":
        set_status(state, "Only .md files are supported.")
        return

    if path.exists() and not path.is_file():
        set_status(state, f"Not a file: {path}")
        return

    try:
        if path.exists():
            state.lines = load_file(path)
            set_status(state, f"Opened: {path}")
        else:
            state.lines = [""]
            set_status(state, f"New file: {path}")
        state.file_path = path
        state.cursor_y = 0
        state.cursor_x = 0
        state.left_scroll_y = 0
        state.left_scroll_x = 0
        state.preview_scroll_y = 0
        state.dirty = False
    except OSError as exc:
        set_status(state, f"Open failed: {exc}")


def new_file_flow(stdscr: curses.window, state: EditorState) -> None:
    if state.dirty and not confirm(stdscr, "Unsaved changes. Create new file?"):
        set_status(state, "New file canceled.")
        return

    state.lines = [""]
    state.file_path = None
    state.cursor_y = 0
    state.cursor_x = 0
    state.left_scroll_y = 0
    state.left_scroll_x = 0
    state.preview_scroll_y = 0
    state.dirty = False
    set_status(state, "New Markdown file.")


def save_flow(stdscr: curses.window, state: EditorState) -> None:
    path = state.file_path
    if path is None:
        default_name = "MarkdownMatrix.md"
        raw = prompt_input(stdscr, f"Save as .md path [{default_name}]: ")
        raw = raw or default_name
        path = Path(raw).expanduser()

    if path.suffix.lower() != ".md":
        set_status(state, "Save failed: file must end with .md")
        return

    try:
        save_file(path, state.lines)
        state.file_path = path
        state.dirty = False
        set_status(state, f"Saved: {path}")
    except OSError as exc:
        set_status(state, f"Save failed: {exc}")


def insert_char(state: EditorState, ch: str) -> None:
    line = state.lines[state.cursor_y]
    state.lines[state.cursor_y] = line[: state.cursor_x] + ch + line[state.cursor_x :]
    state.cursor_x += len(ch)
    state.preferred_x = state.cursor_x
    state.dirty = True


def backspace(state: EditorState) -> None:
    if state.cursor_x > 0:
        line = state.lines[state.cursor_y]
        state.lines[state.cursor_y] = line[: state.cursor_x - 1] + line[state.cursor_x :]
        state.cursor_x -= 1
    elif state.cursor_y > 0:
        prev = state.lines[state.cursor_y - 1]
        current = state.lines[state.cursor_y]
        state.cursor_x = len(prev)
        state.lines[state.cursor_y - 1] = prev + current
        del state.lines[state.cursor_y]
        state.cursor_y -= 1
    state.preferred_x = state.cursor_x
    state.dirty = True


def delete_forward(state: EditorState) -> None:
    line = state.lines[state.cursor_y]
    if state.cursor_x < len(line):
        state.lines[state.cursor_y] = line[: state.cursor_x] + line[state.cursor_x + 1 :]
    elif state.cursor_y < len(state.lines) - 1:
        state.lines[state.cursor_y] = line + state.lines[state.cursor_y + 1]
        del state.lines[state.cursor_y + 1]
    else:
        return
    state.dirty = True


def newline(state: EditorState) -> None:
    line = state.lines[state.cursor_y]
    left = line[: state.cursor_x]
    right = line[state.cursor_x :]
    state.lines[state.cursor_y] = left
    state.lines.insert(state.cursor_y + 1, right)
    state.cursor_y += 1
    state.cursor_x = 0
    state.preferred_x = 0
    state.dirty = True


def handle_left_input(
    stdscr: curses.window,
    state: EditorState,
    key: int,
    body_h: int,
    editor_text_w: int,
) -> bool:
    if key in (17, curses.KEY_F10):  # Ctrl+Q or F10
        if state.dirty and not confirm(stdscr, "Unsaved changes. Quit anyway?"):
            set_status(state, "Quit canceled.")
            return False
        return True
    if key in (19, curses.KEY_F2):  # Ctrl+S or F2
        save_flow(stdscr, state)
        return False
    if key in (15, curses.KEY_F3):  # Ctrl+O or F3
        open_flow(stdscr, state)
        return False
    if key in (14, curses.KEY_F4):  # Ctrl+N or F4
        new_file_flow(stdscr, state)
        return False
    if key == curses.KEY_F6:
        state.focus = "right"
        set_status(state, "Preview focused (F6 to return).")
        return False

    if key == curses.KEY_LEFT:
        if state.cursor_x > 0:
            state.cursor_x -= 1
        elif state.cursor_y > 0:
            state.cursor_y -= 1
            state.cursor_x = len(state.lines[state.cursor_y])
        state.preferred_x = state.cursor_x
    elif key == curses.KEY_RIGHT:
        if state.cursor_x < len(state.lines[state.cursor_y]):
            state.cursor_x += 1
        elif state.cursor_y < len(state.lines) - 1:
            state.cursor_y += 1
            state.cursor_x = 0
        state.preferred_x = state.cursor_x
    elif key == curses.KEY_UP:
        if state.cursor_y > 0:
            state.cursor_y -= 1
            state.cursor_x = min(len(state.lines[state.cursor_y]), state.preferred_x)
    elif key == curses.KEY_DOWN:
        if state.cursor_y < len(state.lines) - 1:
            state.cursor_y += 1
            state.cursor_x = min(len(state.lines[state.cursor_y]), state.preferred_x)
    elif key == curses.KEY_HOME:
        state.cursor_x = 0
        state.preferred_x = 0
    elif key == curses.KEY_END:
        state.cursor_x = len(state.lines[state.cursor_y])
        state.preferred_x = state.cursor_x
    elif key == curses.KEY_PPAGE:
        state.cursor_y = max(0, state.cursor_y - body_h)
        state.cursor_x = min(len(state.lines[state.cursor_y]), state.preferred_x)
    elif key == curses.KEY_NPAGE:
        state.cursor_y = min(len(state.lines) - 1, state.cursor_y + body_h)
        state.cursor_x = min(len(state.lines[state.cursor_y]), state.preferred_x)
    elif key in (10, 13):
        newline(state)
    elif key in (curses.KEY_BACKSPACE, 127, 8):
        backspace(state)
    elif key == curses.KEY_DC:
        delete_forward(state)
    elif key == 9:
        insert_char(state, "    ")
    elif 32 <= key <= 126:
        insert_char(state, chr(key))

    keep_cursor_in_bounds(state)
    ensure_cursor_visible(state, body_h, max(1, editor_text_w))
    return False


def handle_right_input(state: EditorState, key: int, body_h: int, max_preview_scroll: int) -> bool:
    if key == curses.KEY_F6:
        state.focus = "left"
        set_status(state, "Editor focused.")
        return False
    if key in (17, curses.KEY_F10):  # Ctrl+Q or F10
        return True
    if key == curses.KEY_UP:
        state.preview_scroll_y = max(0, state.preview_scroll_y - 1)
    elif key == curses.KEY_DOWN:
        state.preview_scroll_y = min(max_preview_scroll, state.preview_scroll_y + 1)
    elif key == curses.KEY_PPAGE:
        state.preview_scroll_y = max(0, state.preview_scroll_y - body_h)
    elif key == curses.KEY_NPAGE:
        state.preview_scroll_y = min(max_preview_scroll, state.preview_scroll_y + body_h)
    return False


def draw(stdscr: curses.window, state: EditorState) -> tuple[int, int, int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    if h < 12 or w < 70:
        msg = "Terminal too small for MarkdownMatrix (need at least 70x12)."
        stdscr.addnstr(0, 0, msg, max(1, w - 1), curses.color_pair(2))
        stdscr.refresh()
        return 0, 0, 0, 0

    stdscr.attron(curses.color_pair(1))
    stdscr.box()
    title = f" MarkdownMatrix - {state.file_label()} {'*' if state.dirty else ''} "
    stdscr.addnstr(0, 2, title, max(1, w - 4))
    stdscr.attroff(curses.color_pair(1))

    left_w = max(30, (w - 3) // 2)
    sep_x = left_w + 1

    body_top = 2
    body_bottom = h - 4
    body_h = max(1, body_bottom - body_top + 1)

    stdscr.vline(1, sep_x, curses.ACS_VLINE, h - 2)
    left_header = "Markdown Source <" if state.focus == "left" else "Markdown Source"
    right_header = "Live Preview <" if state.focus == "right" else "Live Preview"
    stdscr.addnstr(1, 2, left_header, left_w - 2, curses.color_pair(3))
    stdscr.addnstr(1, sep_x + 2, right_header, w - sep_x - 3, curses.color_pair(3))

    ln_width = max(4, len(str(len(state.lines))))
    editor_text_w = max(10, left_w - ln_width - 4)

    for row in range(body_h):
        line_idx = state.left_scroll_y + row
        y = body_top + row
        if line_idx >= len(state.lines):
            break
        line_no = str(line_idx + 1).rjust(ln_width - 1) + " "
        stdscr.addnstr(y, 2, line_no, ln_width, curses.color_pair(1))
        visible = state.lines[line_idx][state.left_scroll_x : state.left_scroll_x + editor_text_w]
        stdscr.addnstr(y, 2 + ln_width, visible, editor_text_w, curses.color_pair(2))

    preview_gutter_w = 6
    preview_text_w = max(12, w - sep_x - 3 - preview_gutter_w)
    preview_lines = render_preview(state.lines, preview_text_w)
    max_preview_scroll = max(0, len(preview_lines) - body_h)
    state.preview_scroll_y = min(state.preview_scroll_y, max_preview_scroll)

    preview_visible = preview_lines[state.preview_scroll_y : state.preview_scroll_y + body_h]
    for row, (gutter, content) in enumerate(preview_visible):
        y = body_top + row
        gutter_cell = gutter[: preview_gutter_w - 1].rjust(preview_gutter_w - 1) + " "
        stdscr.addnstr(y, sep_x + 2, gutter_cell, preview_gutter_w, curses.color_pair(3))
        stdscr.addnstr(
            y,
            sep_x + 2 + preview_gutter_w,
            content,
            preview_text_w,
            curses.color_pair(2),
        )

    stdscr.addnstr(h - 3, 2, HELP_TEXT, w - 4, curses.color_pair(3))
    focus_status = "EDITOR" if state.focus == "left" else "PREVIEW"
    status = f"[{focus_status}] {state.status}"
    stdscr.addnstr(h - 2, 2, status[: max(0, w - 4)], max(0, w - 4), curses.color_pair(2))

    if state.focus == "left":
        cursor_y = body_top + (state.cursor_y - state.left_scroll_y)
        cursor_x = 2 + ln_width + (state.cursor_x - state.left_scroll_x)
        if body_top <= cursor_y <= body_bottom and 2 <= cursor_x < sep_x:
            curses.curs_set(1)
            stdscr.move(cursor_y, cursor_x)
        else:
            curses.curs_set(0)
    else:
        curses.curs_set(0)

    stdscr.refresh()
    return body_h, left_w, editor_text_w, max_preview_scroll


def app(stdscr: curses.window, start_path: Path | None) -> None:
    curses.curs_set(1)
    curses.start_color()
    curses.use_default_colors()

    # Match the nmap_tui matrix palette.
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)

    stdscr.keypad(True)

    state = EditorState()
    if start_path is not None:
        try:
            if start_path.exists():
                state.lines = load_file(start_path)
                state.status = f"Opened: {start_path}"
            else:
                state.lines = [""]
                state.status = f"New file: {start_path}"
            state.file_path = start_path
            state.dirty = False
        except OSError as exc:
            state.status = f"Open failed: {exc}"

    while True:
        body_h, _, editor_text_w, max_preview_scroll = draw(stdscr, state)
        key = stdscr.getch()

        if state.focus == "left":
            should_quit = handle_left_input(stdscr, state, key, max(1, body_h), editor_text_w)
        else:
            should_quit = handle_right_input(state, key, max(1, body_h), max_preview_scroll)
            if should_quit and state.dirty:
                if not confirm(stdscr, "Unsaved changes. Quit anyway?"):
                    set_status(state, "Quit canceled.")
                    should_quit = False

        if should_quit:
            return


def parse_start_path(argv: list[str]) -> Path | None:
    if len(argv) < 2:
        return None
    path = Path(argv[1]).expanduser()
    if path.suffix.lower() != ".md":
        print("[ERROR] MarkdownMatrix only supports .md files.")
        raise SystemExit(1)
    return path


def main() -> None:
    start_path = parse_start_path(sys.argv)
    try:
        curses.wrapper(lambda stdscr: app(stdscr, start_path))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except curses.error:
        print("Terminal too small or unsupported for curses UI.")


if __name__ == "__main__":
    main()
