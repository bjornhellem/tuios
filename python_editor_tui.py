#!/usr/bin/env python3
"""PyEdit: Matrix-themed Python editor for TuiOS."""

from __future__ import annotations

import curses
import io
import keyword
import subprocess
import sys
import termios
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

import menu_bar

APP_TITLE = "PyEdit"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent

INDENT_WIDTH = 4
HELP_TEXT_LINES = [
    "File: Ctrl+S save  Ctrl+O open  Ctrl+N new  Ctrl+T tab  Ctrl+W close  Ctrl+Q quit  F7/F8 tabs",
    "Edit: Ctrl+F find  F4 next  Ctrl+H replace  Ctrl+G goto  F2 select  F3 clear  Ctrl+C/X/D copy/cut/del  F5 run  F6 clean  F12 hide menu",
]
HELP_HIDDEN_TEXT = "Menu hidden. Press F12 to show."


@dataclass
class Buffer:
    lines: list[str] = field(default_factory=lambda: [""])
    file_path: Path | None = None
    cursor_y: int = 0
    cursor_x: int = 0
    preferred_x: int = 0
    scroll_y: int = 0
    scroll_x: int = 0
    dirty: bool = False
    selecting: bool = False
    selection_start: int | None = None
    selection_end: int | None = None

    def file_label(self) -> str:
        if self.file_path is None:
            return "[New File]"
        return str(self.file_path)

    def tab_label(self) -> str:
        if self.file_path is None:
            return "[New]"
        return self.file_path.name


@dataclass
class EditorState:
    buffers: list[Buffer] = field(default_factory=lambda: [Buffer()])
    active: int = 0
    clipboard: list[str] = field(default_factory=list)
    last_search: str = ""
    status: str = "Ready"
    show_help: bool = True


@dataclass(frozen=True)
class TokenSpan:
    start: int
    end: int
    style: str


def current_buffer(state: EditorState) -> Buffer:
    return state.buffers[state.active]


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


def truncate_text(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def load_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if text.endswith("\n"):
        lines.append("")
    return lines or [""]


def save_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def set_status(state: EditorState, message: str) -> None:
    state.status = message


def keep_cursor_in_bounds(buf: Buffer) -> None:
    buf.cursor_y = max(0, min(buf.cursor_y, len(buf.lines) - 1))
    buf.cursor_x = max(0, min(buf.cursor_x, len(buf.lines[buf.cursor_y])))


def ensure_cursor_visible(buf: Buffer, body_h: int, editor_w: int) -> None:
    if buf.cursor_y < buf.scroll_y:
        buf.scroll_y = buf.cursor_y
    elif buf.cursor_y >= buf.scroll_y + body_h:
        buf.scroll_y = buf.cursor_y - body_h + 1

    if buf.cursor_x < buf.scroll_x:
        buf.scroll_x = buf.cursor_x
    elif buf.cursor_x >= buf.scroll_x + editor_w:
        buf.scroll_x = buf.cursor_x - editor_w + 1

    buf.scroll_y = max(0, buf.scroll_y)
    buf.scroll_x = max(0, buf.scroll_x)


def reset_view(buf: Buffer) -> None:
    buf.cursor_y = 0
    buf.cursor_x = 0
    buf.preferred_x = 0
    buf.scroll_y = 0
    buf.scroll_x = 0


def clear_selection(buf: Buffer) -> None:
    buf.selecting = False
    buf.selection_start = None
    buf.selection_end = None


def has_selection(buf: Buffer) -> bool:
    return buf.selection_start is not None and buf.selection_end is not None


def selection_range(buf: Buffer) -> tuple[int, int] | None:
    if not has_selection(buf):
        return None
    start = buf.selection_start
    end = buf.selection_end
    if start is None or end is None:
        return None
    return (start, end) if start <= end else (end, start)


def update_selection(buf: Buffer) -> None:
    if buf.selecting and buf.selection_start is not None:
        buf.selection_end = buf.cursor_y


def delete_selection(buf: Buffer) -> bool:
    rng = selection_range(buf)
    if rng is None:
        return False
    start, end = rng
    start = max(0, min(start, len(buf.lines) - 1))
    end = max(0, min(end, len(buf.lines) - 1))
    if start > end:
        return False

    del buf.lines[start : end + 1]
    if not buf.lines:
        buf.lines = [""]
    buf.cursor_y = min(start, len(buf.lines) - 1)
    buf.cursor_x = 0
    buf.preferred_x = 0
    buf.dirty = True
    clear_selection(buf)
    return True


def insert_char(buf: Buffer, ch: str) -> None:
    if has_selection(buf) and not buf.selecting:
        delete_selection(buf)
    line = buf.lines[buf.cursor_y]
    buf.lines[buf.cursor_y] = line[: buf.cursor_x] + ch + line[buf.cursor_x :]
    buf.cursor_x += len(ch)
    buf.preferred_x = buf.cursor_x
    buf.dirty = True


def newline(buf: Buffer) -> None:
    if has_selection(buf) and not buf.selecting:
        delete_selection(buf)
    line = buf.lines[buf.cursor_y]
    before = line[: buf.cursor_x]
    after = line[buf.cursor_x :]
    indent = len(before) - len(before.lstrip(" "))
    extra = INDENT_WIDTH if before.rstrip().endswith(":") else 0
    buf.lines[buf.cursor_y] = before
    buf.lines.insert(buf.cursor_y + 1, " " * (indent + extra) + after.lstrip(" "))
    buf.cursor_y += 1
    buf.cursor_x = indent + extra
    buf.preferred_x = buf.cursor_x
    buf.dirty = True


def backspace(buf: Buffer) -> None:
    if has_selection(buf) and not buf.selecting:
        delete_selection(buf)
        return
    if buf.cursor_x > 0:
        line = buf.lines[buf.cursor_y]
        buf.lines[buf.cursor_y] = line[: buf.cursor_x - 1] + line[buf.cursor_x :]
        buf.cursor_x -= 1
        buf.preferred_x = buf.cursor_x
        buf.dirty = True
        return

    if buf.cursor_y == 0:
        return

    prev_line = buf.lines[buf.cursor_y - 1]
    curr_line = buf.lines[buf.cursor_y]
    buf.cursor_x = len(prev_line)
    buf.lines[buf.cursor_y - 1] = prev_line + curr_line
    buf.lines.pop(buf.cursor_y)
    buf.cursor_y -= 1
    buf.preferred_x = buf.cursor_x
    buf.dirty = True


def delete_forward(buf: Buffer) -> None:
    if has_selection(buf) and not buf.selecting:
        delete_selection(buf)
        return
    line = buf.lines[buf.cursor_y]
    if buf.cursor_x < len(line):
        buf.lines[buf.cursor_y] = line[: buf.cursor_x] + line[buf.cursor_x + 1 :]
        buf.dirty = True
        return

    if buf.cursor_y >= len(buf.lines) - 1:
        return

    next_line = buf.lines[buf.cursor_y + 1]
    buf.lines[buf.cursor_y] = line + next_line
    buf.lines.pop(buf.cursor_y + 1)
    buf.dirty = True


def open_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    if buf.dirty and not confirm(stdscr, "Unsaved changes. Open anyway?"):
        set_status(state, "Open canceled.")
        return

    path_raw = prompt_input(stdscr, "Open .py file path: ", str(buf.file_path) if buf.file_path else "")
    if not path_raw:
        set_status(state, "Open canceled.")
        return

    path = Path(path_raw).expanduser()
    try:
        if path.exists():
            buf.lines = load_file(path)
            set_status(state, f"Opened: {path}")
        else:
            buf.lines = [""]
            set_status(state, f"New file: {path}")
        buf.file_path = path
        buf.dirty = False
        reset_view(buf)
        clear_selection(buf)
    except OSError as exc:
        set_status(state, f"Open failed: {exc}")


def save_flow(stdscr: curses.window, state: EditorState) -> bool:
    buf = current_buffer(state)
    path = buf.file_path
    if path is None:
        path_raw = prompt_input(stdscr, "Save as .py file path: ")
        if not path_raw:
            set_status(state, "Save canceled.")
            return False
        path = Path(path_raw).expanduser()
        buf.file_path = path

    try:
        save_file(path, buf.lines)
    except OSError as exc:
        set_status(state, f"Save failed: {exc}")
        return False

    buf.dirty = False
    set_status(state, f"Saved: {path}")
    return True


def new_file_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    if buf.dirty and not confirm(stdscr, "Unsaved changes. New file anyway?"):
        set_status(state, "New file canceled.")
        return
    buf.lines = [""]
    buf.file_path = None
    buf.dirty = False
    reset_view(buf)
    clear_selection(buf)
    set_status(state, "New file ready.")


def new_tab_flow(state: EditorState) -> None:
    state.buffers.append(Buffer())
    state.active = len(state.buffers) - 1
    set_status(state, f"New tab {state.active + 1}.")


def close_tab_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    if buf.dirty and not confirm(stdscr, "Unsaved changes. Close tab anyway?"):
        set_status(state, "Close canceled.")
        return
    if len(state.buffers) == 1:
        new_file_flow(stdscr, state)
        return
    state.buffers.pop(state.active)
    state.active = max(0, min(state.active, len(state.buffers) - 1))
    set_status(state, f"Switched to tab {state.active + 1}.")


def switch_tab(state: EditorState, delta: int) -> None:
    if not state.buffers:
        return
    state.active = (state.active + delta) % len(state.buffers)
    set_status(state, f"Switched to tab {state.active + 1}.")


def run_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    if buf.file_path is None:
        path_raw = prompt_input(stdscr, "Save path before run: ")
        if not path_raw:
            set_status(state, "Run canceled (no path).")
            return
        buf.file_path = Path(path_raw).expanduser()

    if buf.dirty:
        if not confirm(stdscr, "Save before run?"):
            set_status(state, "Run canceled (unsaved changes).")
            return

    if not save_flow(stdscr, state):
        return

    path = buf.file_path
    if path is None:
        set_status(state, "Run failed (missing path).")
        return

    curses.def_prog_mode()
    curses.endwin()
    try:
        print(f"\n[PyEdit] Running {path} ...\n")
        proc = subprocess.run([sys.executable, str(path)], check=False)
        input("\n[PyEdit] Press Enter to return to editor...")
        exit_code = proc.returncode
    finally:
        curses.reset_prog_mode()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.clear()
        stdscr.refresh()

    set_status(state, f"Run complete (exit {exit_code}).")


def compute_indents(lines: list[str]) -> tuple[dict[int, int], set[int]] | None:
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"

    line_indents: dict[int, int] = {}
    skip_lines: set[int] = set()
    current_indent = 0
    paren_level = 0

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            tok_type = tok.type
            start_line, _ = tok.start
            end_line, _ = tok.end

            if tok_type == tokenize.OP:
                if tok.string in "([{":
                    paren_level += 1
                elif tok.string in ")]}":
                    paren_level = max(0, paren_level - 1)

            if tok_type == tokenize.STRING and start_line != end_line:
                for line_no in range(start_line, end_line + 1):
                    skip_lines.add(line_no)

            if paren_level > 0:
                skip_lines.add(start_line)

            if tok_type == tokenize.INDENT:
                current_indent += 1
                if start_line not in skip_lines:
                    line_indents[start_line] = current_indent
            elif tok_type == tokenize.DEDENT:
                current_indent = max(0, current_indent - 1)
                if start_line not in skip_lines:
                    line_indents[start_line] = current_indent
            elif tok_type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING, tokenize.ENDMARKER):
                if start_line not in skip_lines and start_line not in line_indents:
                    line_indents[start_line] = current_indent
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None

    return line_indents, skip_lines


def cleanup_indentation(lines: list[str]) -> tuple[list[str], str]:
    computed = compute_indents(lines)
    if computed is None:
        cleaned: list[str] = []
        for raw in lines:
            prefix_len = len(raw) - len(raw.lstrip(" \t"))
            prefix = raw[:prefix_len].replace("\t", " " * INDENT_WIDTH)
            rest = raw[prefix_len:]
            cleaned.append((prefix + rest).rstrip())
        return cleaned or [""], "Cleanup: normalized tabs + trailing whitespace (parse failed)."

    line_indents, skip_lines = computed
    cleaned = []
    for idx, raw in enumerate(lines, start=1):
        if idx in skip_lines:
            cleaned.append(raw)
            continue

        prefix_len = len(raw) - len(raw.lstrip(" \t"))
        prefix = raw[:prefix_len].replace("\t", " " * INDENT_WIDTH)
        raw = prefix + raw[prefix_len:]

        stripped = raw.rstrip()
        if not stripped:
            cleaned.append("")
            continue
        indent_level = line_indents.get(idx, 0)
        content = stripped.lstrip(" ")
        cleaned.append(" " * (indent_level * INDENT_WIDTH) + content)

    return cleaned or [""], "Indentation normalized to 4 spaces."


def cleanup_flow(state: EditorState) -> None:
    buf = current_buffer(state)
    cleaned, message = cleanup_indentation(buf.lines)
    if cleaned != buf.lines:
        buf.lines = cleaned
        buf.dirty = True
    set_status(state, message)
    keep_cursor_in_bounds(buf)


def copy_selection(state: EditorState) -> None:
    buf = current_buffer(state)
    rng = selection_range(buf)
    if rng is None:
        set_status(state, "Copy: no selection.")
        return
    start, end = rng
    state.clipboard = list(buf.lines[start : end + 1])
    set_status(state, f"Copied lines {start + 1}-{end + 1}.")


def cut_selection(state: EditorState) -> None:
    buf = current_buffer(state)
    rng = selection_range(buf)
    if rng is None:
        set_status(state, "Cut: no selection.")
        return
    start, end = rng
    state.clipboard = list(buf.lines[start : end + 1])
    delete_selection(buf)
    set_status(state, f"Cut lines {start + 1}-{end + 1}.")


def delete_selection_flow(state: EditorState) -> None:
    buf = current_buffer(state)
    rng = selection_range(buf)
    if rng is None:
        set_status(state, "Delete: no selection.")
        return
    start, end = rng
    delete_selection(buf)
    set_status(state, f"Deleted lines {start + 1}-{end + 1}.")


def find_next(state: EditorState) -> None:
    buf = current_buffer(state)
    query = state.last_search
    if not query:
        set_status(state, "Find: no search term.")
        return

    start_line = buf.cursor_y
    start_col = buf.cursor_x + 1

    for line_idx in range(start_line, len(buf.lines)):
        line = buf.lines[line_idx]
        col = start_col if line_idx == start_line else 0
        pos = line.find(query, col)
        if pos != -1:
            buf.cursor_y = line_idx
            buf.cursor_x = pos
            buf.preferred_x = buf.cursor_x
            set_status(state, f"Found '{query}' at line {line_idx + 1}.")
            return

    for line_idx in range(0, start_line + 1):
        line = buf.lines[line_idx]
        pos = line.find(query, 0)
        if pos != -1:
            buf.cursor_y = line_idx
            buf.cursor_x = pos
            buf.preferred_x = buf.cursor_x
            set_status(state, f"Wrapped to '{query}' at line {line_idx + 1}.")
            return

    set_status(state, f"'{query}' not found.")


def search_flow(stdscr: curses.window, state: EditorState) -> None:
    query = prompt_input(stdscr, "Find: ", state.last_search)
    if not query:
        set_status(state, "Find canceled.")
        return
    state.last_search = query
    find_next(state)


def replace_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    query = prompt_input(stdscr, "Replace: find: ", state.last_search)
    if not query:
        set_status(state, "Replace canceled.")
        return
    replacement = prompt_input(stdscr, "Replace with: ")
    count = 0
    new_lines = []
    for line in buf.lines:
        if query in line:
            count += line.count(query)
            line = line.replace(query, replacement)
        new_lines.append(line)
    buf.lines = new_lines
    if count > 0:
        buf.dirty = True
    state.last_search = query
    set_status(state, f"Replaced {count} occurrence(s).")


def goto_flow(stdscr: curses.window, state: EditorState) -> None:
    buf = current_buffer(state)
    raw = prompt_input(stdscr, "Go to line: ")
    if not raw:
        set_status(state, "Go to canceled.")
        return
    try:
        line_no = int(raw)
    except ValueError:
        set_status(state, "Go to failed (invalid number).")
        return
    line_no = max(1, min(line_no, len(buf.lines)))
    buf.cursor_y = line_no - 1
    buf.cursor_x = 0
    buf.preferred_x = 0
    set_status(state, f"Jumped to line {line_no}.")


def build_syntax_spans(lines: list[str]) -> dict[int, list[TokenSpan]]:
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"

    spans: dict[int, list[TokenSpan]] = {}

    def add_span(line_no: int, start_col: int, end_col: int, style: str) -> None:
        if end_col <= start_col:
            return
        spans.setdefault(line_no, []).append(TokenSpan(start_col, end_col, style))

    builtins = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
    pending_def = False
    pending_class = False
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            tok_type = tok.type
            start_line, start_col = tok.start
            end_line, end_col = tok.end

            style = ""
            if tok_type == tokenize.COMMENT:
                style = "comment"
            elif tok_type == tokenize.STRING:
                style = "string"
            elif tok_type == tokenize.NUMBER:
                style = "number"
            elif tok_type == tokenize.OP and tok.string == "@":
                style = "decorator"
            elif tok_type == tokenize.NAME:
                if tok.string in keyword.kwlist:
                    style = "keyword"
                    if tok.string == "def":
                        pending_def = True
                        pending_class = False
                    elif tok.string == "class":
                        pending_class = True
                        pending_def = False
                elif pending_def:
                    style = "defname"
                    pending_def = False
                elif pending_class:
                    style = "classname"
                    pending_class = False
                elif tok.string in builtins:
                    style = "builtin"

            if not style:
                continue

            if start_line == end_line:
                add_span(start_line, start_col, end_col, style)
            else:
                if 0 <= start_line - 1 < len(lines):
                    add_span(start_line, start_col, len(lines[start_line - 1]), style)
                for line_no in range(start_line + 1, end_line):
                    if 0 <= line_no - 1 < len(lines):
                        add_span(line_no, 0, len(lines[line_no - 1]), style)
                add_span(end_line, 0, end_col, style)
    except (tokenize.TokenError, IndentationError):
        return {}

    for line_no in spans:
        spans[line_no].sort(key=lambda span: span.start)
    return spans


def style_attr(style: str) -> int:
    base = curses.color_pair(2)
    if style == "comment":
        return curses.color_pair(4) | curses.A_DIM
    if style == "string":
        return curses.color_pair(5)
    if style == "number":
        return curses.color_pair(6)
    if style == "keyword":
        return curses.color_pair(7) | curses.A_BOLD
    if style == "builtin":
        return curses.color_pair(8)
    if style in {"defname", "classname"}:
        return curses.color_pair(9) | curses.A_BOLD
    if style == "decorator":
        return curses.color_pair(10)
    return base


def tabs_bar(state: EditorState, width: int) -> str:
    labels = []
    for idx, buf in enumerate(state.buffers, start=1):
        label = buf.tab_label()
        if buf.dirty:
            label += "*"
        if idx - 1 == state.active:
            labels.append(f"[{idx}:{label}]")
        else:
            labels.append(f" {idx}:{label} ")
    text = " ".join(labels) if labels else "[1:New]"
    return truncate_text(text, max(1, width))


def draw_highlighted_line(
    stdscr: curses.window,
    y: int,
    x: int,
    line: str,
    spans: list[TokenSpan],
    visible_start: int,
    width: int,
) -> None:
    visible_end = visible_start + width
    pos = visible_start

    for span in spans:
        if span.end <= visible_start:
            continue
        if span.start >= visible_end:
            break
        if pos < span.start:
            segment = line[pos: min(span.start, visible_end)]
            stdscr.addnstr(y, x + (pos - visible_start), segment, width - (pos - visible_start), curses.color_pair(2))
        seg_start = max(span.start, visible_start)
        seg_end = min(span.end, visible_end)
        if seg_start < seg_end:
            segment = line[seg_start:seg_end]
            stdscr.addnstr(
                y,
                x + (seg_start - visible_start),
                segment,
                width - (seg_start - visible_start),
                style_attr(span.style),
            )
        pos = max(pos, seg_end)

    if pos < visible_end:
        segment = line[pos:visible_end]
        stdscr.addnstr(y, x + (pos - visible_start), segment, width - (pos - visible_start), curses.color_pair(2))


def draw(stdscr: curses.window, state: EditorState) -> tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    min_height = 13 if state.show_help else 11
    if h < min_height or w < 60:
        msg = f"Terminal too small for PyEdit (need at least 60x{min_height})."
        stdscr.addnstr(0, 0, msg, max(1, w - 1), curses.color_pair(2))
        stdscr.refresh()
        return 0, 0

    buf = current_buffer(state)

    stdscr.attron(curses.color_pair(1))
    stdscr.box()
    title = f" PyEdit - {buf.file_label()} {'*' if buf.dirty else ''} "
    stdscr.addnstr(0, 2, title, max(1, w - 4))
    stdscr.attroff(curses.color_pair(1))

    stdscr.addnstr(1, 2, tabs_bar(state, w - 4), w - 4, curses.color_pair(3))
    stdscr.addnstr(2, 2, "Python Source", w - 4, curses.color_pair(3))

    body_top = 3
    body_bottom = h - 4
    body_h = max(1, body_bottom - body_top + 1)

    ln_width = max(4, len(str(len(buf.lines))) + 1)
    editor_w = max(10, w - ln_width - 4)

    syntax_spans = build_syntax_spans(buf.lines)
    selection = selection_range(buf)

    for row in range(body_h):
        line_idx = buf.scroll_y + row
        y = body_top + row
        if line_idx >= len(buf.lines):
            break
        line_no = str(line_idx + 1).rjust(ln_width - 1) + " "
        line = buf.lines[line_idx]
        is_selected = False
        if selection is not None:
            sel_start, sel_end = selection
            is_selected = sel_start <= line_idx <= sel_end

        if is_selected:
            stdscr.addnstr(y, 2, line_no, ln_width, curses.color_pair(3))
            visible = line[buf.scroll_x : buf.scroll_x + editor_w]
            stdscr.addnstr(y, 2 + ln_width, visible, editor_w, curses.color_pair(3))
            continue

        stdscr.addnstr(y, 2, line_no, ln_width, curses.color_pair(1))
        spans = syntax_spans.get(line_idx + 1, [])
        draw_highlighted_line(stdscr, y, 2 + ln_width, line, spans, buf.scroll_x, editor_w)

    if state.show_help:
        stdscr.addnstr(h - 4, 2, HELP_TEXT_LINES[0], w - 4, curses.color_pair(3))
        stdscr.addnstr(h - 3, 2, HELP_TEXT_LINES[1], w - 4, curses.color_pair(3))
    else:
        stdscr.addnstr(h - 3, 2, HELP_HIDDEN_TEXT, w - 4, curses.color_pair(3))
    status = f"[Tab {state.active + 1}/{len(state.buffers)} | Ln {buf.cursor_y + 1}, Col {buf.cursor_x + 1}] {state.status}"
    stdscr.addnstr(h - 2, 2, status[: max(0, w - 4)], max(0, w - 4), curses.color_pair(2))

    cursor_y = body_top + (buf.cursor_y - buf.scroll_y)
    cursor_x = 2 + ln_width + (buf.cursor_x - buf.scroll_x)
    if body_top <= cursor_y <= body_bottom and 2 + ln_width <= cursor_x < w - 2:
        curses.curs_set(1)
        stdscr.move(cursor_y, cursor_x)
    else:
        curses.curs_set(0)

    stdscr.refresh()
    return body_h, editor_w


def handle_input(stdscr: curses.window, state: EditorState, key: int, body_h: int, editor_w: int) -> bool:
    buf = current_buffer(state)

    if key == 17:  # Ctrl+Q
        if buf.dirty and not confirm(stdscr, "Unsaved changes. Quit anyway?"):
            set_status(state, "Quit canceled.")
            return False
        return True
    if key == curses.KEY_F12:
        state.show_help = not state.show_help
        set_status(state, "Menu shown." if state.show_help else "Menu hidden.")
        return False
    if key == 19:  # Ctrl+S
        save_flow(stdscr, state)
        return False
    if key == 15:  # Ctrl+O
        open_flow(stdscr, state)
        return False
    if key == 14:  # Ctrl+N
        new_file_flow(stdscr, state)
        return False
    if key == 20:  # Ctrl+T
        new_tab_flow(state)
        return False
    if key == 23:  # Ctrl+W
        close_tab_flow(stdscr, state)
        return False
    if key == 6:  # Ctrl+F
        search_flow(stdscr, state)
        return False
    if key == curses.KEY_F4:
        find_next(state)
        return False
    if key == 8:  # Ctrl+H
        replace_flow(stdscr, state)
        return False
    if key == 7:  # Ctrl+G
        goto_flow(stdscr, state)
        return False
    if key == 3:  # Ctrl+C
        copy_selection(state)
        return False
    if key == 24:  # Ctrl+X
        cut_selection(state)
        return False
    if key == 4:  # Ctrl+D
        delete_selection_flow(state)
        return False
    if key == curses.KEY_F2:
        if not buf.selecting:
            buf.selecting = True
            buf.selection_start = buf.cursor_y
            buf.selection_end = buf.cursor_y
            set_status(state, f"Selection started at line {buf.cursor_y + 1}.")
        else:
            buf.selecting = False
            buf.selection_end = buf.cursor_y
            set_status(state, "Selection fixed.")
        return False
    if key == curses.KEY_F3:
        clear_selection(buf)
        set_status(state, "Selection cleared.")
        return False
    if key == curses.KEY_F5:
        run_flow(stdscr, state)
        return False
    if key == curses.KEY_F6:
        cleanup_flow(state)
        return False
    if key == curses.KEY_F7:
        switch_tab(state, -1)
        return False
    if key == curses.KEY_F8:
        switch_tab(state, 1)
        return False

    if key == curses.KEY_UP:
        buf.cursor_y = max(0, buf.cursor_y - 1)
        buf.cursor_x = min(len(buf.lines[buf.cursor_y]), buf.preferred_x)
    elif key == curses.KEY_DOWN:
        buf.cursor_y = min(len(buf.lines) - 1, buf.cursor_y + 1)
        buf.cursor_x = min(len(buf.lines[buf.cursor_y]), buf.preferred_x)
    elif key == curses.KEY_LEFT:
        if buf.cursor_x > 0:
            buf.cursor_x -= 1
        elif buf.cursor_y > 0:
            buf.cursor_y -= 1
            buf.cursor_x = len(buf.lines[buf.cursor_y])
        buf.preferred_x = buf.cursor_x
    elif key == curses.KEY_RIGHT:
        if buf.cursor_x < len(buf.lines[buf.cursor_y]):
            buf.cursor_x += 1
        elif buf.cursor_y < len(buf.lines) - 1:
            buf.cursor_y += 1
            buf.cursor_x = 0
        buf.preferred_x = buf.cursor_x
    elif key == curses.KEY_HOME:
        buf.cursor_x = 0
        buf.preferred_x = buf.cursor_x
    elif key == curses.KEY_END:
        buf.cursor_x = len(buf.lines[buf.cursor_y])
        buf.preferred_x = buf.cursor_x
    elif key == curses.KEY_PPAGE:
        buf.cursor_y = max(0, buf.cursor_y - body_h)
        buf.cursor_x = min(len(buf.lines[buf.cursor_y]), buf.preferred_x)
    elif key == curses.KEY_NPAGE:
        buf.cursor_y = min(len(buf.lines) - 1, buf.cursor_y + body_h)
        buf.cursor_x = min(len(buf.lines[buf.cursor_y]), buf.preferred_x)
    elif key in (10, 13):
        newline(buf)
    elif key in (curses.KEY_BACKSPACE, 127, 8):
        backspace(buf)
    elif key == curses.KEY_DC:
        delete_forward(buf)
    elif key == 9:
        insert_char(buf, " " * INDENT_WIDTH)
    elif 32 <= key <= 126:
        insert_char(buf, chr(key))

    update_selection(buf)
    keep_cursor_in_bounds(buf)
    ensure_cursor_visible(buf, body_h, editor_w)
    return False


def parse_start_path(argv: list[str]) -> Path | None:
    if len(argv) < 2:
        return None
    return Path(argv[1]).expanduser()


def app(stdscr: curses.window, start_path: Path | None) -> None:
    root = stdscr
    stdscr = menu_bar.content_window(root)
    curses.curs_set(1)
    curses.start_color()
    curses.use_default_colors()

    # Match the TuiOS palette.
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)     # comments
    curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)  # strings
    curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLACK)   # numbers
    curses.init_pair(7, curses.COLOR_BLUE, curses.COLOR_BLACK)     # keywords
    curses.init_pair(8, curses.COLOR_CYAN, curses.COLOR_BLACK)     # builtins
    curses.init_pair(9, curses.COLOR_GREEN, curses.COLOR_BLACK)    # def/class names
    curses.init_pair(10, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # decorators

    root.keypad(True)
    stdscr.keypad(True)

    state = EditorState()
    stdin_fd = sys.stdin.fileno()
    old_term_settings = termios.tcgetattr(stdin_fd)
    new_settings = termios.tcgetattr(stdin_fd)
    # Disable XON/XOFF so Ctrl+Q/Ctrl+S reach the app.
    # termios attrs: [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    new_settings[0] = new_settings[0] & ~termios.IXON & ~termios.IXOFF
    termios.tcsetattr(stdin_fd, termios.TCSANOW, new_settings)
    if start_path is not None:
        buf = current_buffer(state)
        try:
            if start_path.exists():
                buf.lines = load_file(start_path)
                state.status = f"Opened: {start_path}"
            else:
                buf.lines = [""]
                state.status = f"New file: {start_path}"
            buf.file_path = start_path
            buf.dirty = False
        except OSError as exc:
            state.status = f"Open failed: {exc}"

    try:
        while True:
            body_h, editor_w = draw(stdscr, state)
            menu_bar.draw_menu_bar(root, APP_TITLE, False)
            root.refresh()
            key = stdscr.getch()
            if key == -1:
                continue
            if key == curses.KEY_F1:
                choice = menu_bar.open_menu(root, APP_TITLE, ROOT_DIR, THIS_FILE)
                if choice == menu_bar.EXIT_ACTION:
                    return
                if isinstance(choice, Path):
                    menu_bar.switch_to_app(choice)
                continue
            should_quit = handle_input(stdscr, state, key, max(1, body_h), max(1, editor_w))
            if should_quit:
                return
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSANOW, old_term_settings)


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
