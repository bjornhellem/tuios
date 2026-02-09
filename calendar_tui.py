#!/usr/bin/env python3
"""Matrix-themed calendar TUI for TuiOS."""

from __future__ import annotations

import calendar
import curses
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import menu_bar

APP_TITLE = "Matrix Calendar"
THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent
EVENTS_FILE = ROOT_DIR / "calendar_events.json"
DEFAULT_TIMEOUT = 200

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
VIEW_MODES = ("week", "month", "year", "list")


@dataclass
class Event:
    id: str
    title: str
    date: str  # YYYY-MM-DD
    start: str | None = None  # HH:MM
    end: str | None = None  # HH:MM
    all_day: bool = False
    notes: str | None = None


def load_events(path: Path) -> list[Event]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    events: list[Event] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            date = str(item.get("date", "")).strip()
            if not title or not date:
                continue
            events.append(
                Event(
                    id=str(item.get("id", "")) or make_event_id(),
                    title=title,
                    date=date,
                    start=item.get("start") or None,
                    end=item.get("end") or None,
                    all_day=bool(item.get("all_day", False)),
                    notes=item.get("notes") or None,
                )
            )
    return events


def save_events(path: Path, events: Iterable[Event]) -> None:
    payload = []
    for event in events:
        payload.append(
            {
                "id": event.id,
                "title": event.title,
                "date": event.date,
                "start": event.start,
                "end": event.end,
                "all_day": event.all_day,
                "notes": event.notes,
            }
        )
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_event_id() -> str:
    return dt.datetime.now().strftime("EVT%Y%m%d%H%M%S%f")


def parse_date(text: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    if not text:
        return None
    try:
        dt.datetime.strptime(text, "%H:%M")
        return text
    except ValueError:
        return None


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def safe_addnstr(stdscr: curses.window, y: int, x: int, text: str, width: int, color: int) -> None:
    if width <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, width, color)
    except curses.error:
        return


def safe_addch(stdscr: curses.window, y: int, x: int, ch: int | str, color: int) -> None:
    try:
        stdscr.addch(y, x, ch, color)
    except curses.error:
        return


def draw_box(stdscr: curses.window, x: int, y: int, w: int, h: int, color: int) -> None:
    if w < 2 or h < 2:
        return
    hline = curses.ACS_HLINE
    vline = curses.ACS_VLINE
    tl = curses.ACS_ULCORNER
    tr = curses.ACS_URCORNER
    bl = curses.ACS_LLCORNER
    br = curses.ACS_LRCORNER

    for i in range(w):
        safe_addch(stdscr, y, x + i, hline, color)
        safe_addch(stdscr, y + h - 1, x + i, hline, color)
    for j in range(h):
        safe_addch(stdscr, y + j, x, vline, color)
        safe_addch(stdscr, y + j, x + w - 1, vline, color)
    safe_addch(stdscr, y, x, tl, color)
    safe_addch(stdscr, y, x + w - 1, tr, color)
    safe_addch(stdscr, y + h - 1, x, bl, color)
    safe_addch(stdscr, y + h - 1, x + w - 1, br, color)

    for row in range(y + 1, y + h - 1):
        safe_addnstr(stdscr, row, x + 1, " " * (w - 2), w - 2, color)


def prompt_input(stdscr: curses.window, label: str, initial: str = "") -> str:
    h, w = stdscr.getmaxyx()
    row_label = h - 3
    row_input = h - 2

    stdscr.timeout(-1)
    curses.flushinp()
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
    stdscr.timeout(DEFAULT_TIMEOUT)
    return raw.decode("utf-8", errors="ignore").strip()


def set_status(state: dict, message: str) -> None:
    state["status"] = message


def events_on_date(events: Iterable[Event], date: dt.date) -> list[Event]:
    day = date.strftime("%Y-%m-%d")
    matches = [ev for ev in events if ev.date == day]
    def sort_key(ev: Event) -> tuple[int, str]:
        return (0 if ev.all_day else 1, ev.start or "99:99")
    return sorted(matches, key=sort_key)


def event_label(ev: Event) -> str:
    if ev.all_day:
        return f"All day: {ev.title}"
    if ev.start and ev.end:
        return f"{ev.start}-{ev.end} {ev.title}"
    if ev.start:
        return f"{ev.start} {ev.title}"
    return ev.title


def week_start(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def add_days(date: dt.date, days: int) -> dt.date:
    return date + dt.timedelta(days=days)


def add_months(date: dt.date, months: int) -> dt.date:
    year = date.year + (date.month - 1 + months) // 12
    month = (date.month - 1 + months) % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def draw_header(stdscr: curses.window, view_mode: str, selected: dt.date) -> None:
    _, w = stdscr.getmaxyx()
    now = dt.datetime.now().strftime("%H:%M:%S")
    label = f"{APP_TITLE}  [{view_mode.upper()}]  {selected.strftime('%Y-%m-%d')}"
    stdscr.addnstr(0, 0, " " * max(0, w - 1), w - 1, curses.color_pair(3))
    stdscr.addnstr(0, 1, label, max(0, w - 2), curses.color_pair(3))
    right = max(1, w - len(now) - 2)
    stdscr.addnstr(0, right, now, len(now), curses.color_pair(3))


def draw_footer(stdscr: curses.window, status: str) -> None:
    h, w = stdscr.getmaxyx()
    help_line = "Arrows move  W/M/Y/L view  J jump  A add  E edit  T today  Q quit"
    stdscr.addnstr(h - 2, 1, " " * max(0, w - 2), max(0, w - 2), curses.color_pair(2))
    stdscr.addnstr(h - 2, 1, truncate(status, w - 2), max(0, w - 2), curses.color_pair(2))
    stdscr.addnstr(h - 1, 1, truncate(help_line, w - 2), max(0, w - 2), curses.color_pair(3))


def draw_events_panel(
    stdscr: curses.window,
    x: int,
    y: int,
    width: int,
    height: int,
    date: dt.date,
    events: list[Event],
) -> None:
    if width <= 6 or height <= 3:
        return
    title = f"Events {date.strftime('%Y-%m-%d')}"
    safe_addnstr(stdscr, y, x, truncate(title, width - 1), width - 1, curses.color_pair(3))
    for idx in range(1, height):
        safe_addnstr(stdscr, y + idx, x, " " * (width - 1), width - 1, curses.color_pair(1))
    if not events:
        safe_addnstr(stdscr, y + 2, x + 1, "No events", width - 2, curses.color_pair(2))
        return
    row = y + 1
    for ev in events:
        if row >= y + height:
            break
        label = event_label(ev)
        safe_addnstr(stdscr, row, x + 1, truncate(label, width - 2), width - 2, curses.color_pair(2))
        row += 1


def draw_week_view(
    stdscr: curses.window,
    x: int,
    y: int,
    width: int,
    height: int,
    selected: dt.date,
    events: list[Event],
) -> None:
    start = week_start(selected)
    col_base = max(10, width // 7)
    extra_w = max(0, width - (col_base * 7))
    col_widths = [col_base + (1 if i < extra_w else 0) for i in range(7)]

    col_xs = [x]
    for i in range(7):
        col_xs.append(col_xs[-1] + col_widths[i])

    for col in range(7):
        day = start + dt.timedelta(days=col)
        cell_x = col_xs[col]
        cell_w = col_widths[col]
        cell_h = height
        border_color = curses.color_pair(3) if day == selected else curses.color_pair(1)
        draw_box(stdscr, cell_x, y, cell_w, cell_h, border_color)

        label = f"{WEEKDAYS[col]} {day.day:02d}"
        text_color = curses.color_pair(3) if day == selected else curses.color_pair(2)
        safe_addnstr(stdscr, y + 1, cell_x + 2, truncate(label, cell_w - 3), cell_w - 3, text_color)

        day_events = events_on_date(events, day)
        row = y + 2
        for ev in day_events:
            if row >= y + cell_h - 1:
                break
            safe_addnstr(
                stdscr,
                row,
                cell_x + 2,
                truncate(event_label(ev), cell_w - 3),
                cell_w - 3,
                curses.color_pair(2),
            )
            row += 1


def draw_month_view(
    stdscr: curses.window,
    x: int,
    y: int,
    width: int,
    height: int,
    selected: dt.date,
    events: list[Event],
) -> None:
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(selected.year, selected.month)
    weeks = month_days + [[0] * 7 for _ in range(max(0, 6 - len(month_days)))]

    header_h = 1
    grid_top = y + header_h
    grid_h = max(1, height - header_h)

    col_base = max(4, width // 7)
    extra_w = max(0, width - (col_base * 7))
    col_widths = [col_base + (1 if i < extra_w else 0) for i in range(7)]

    row_base = max(3, grid_h // 6)
    extra_h = max(0, grid_h - (row_base * 6))
    row_heights = [row_base + (1 if i < extra_h else 0) for i in range(6)]

    col_xs = [x]
    for i in range(7):
        col_xs.append(col_xs[-1] + col_widths[i])
    row_ys = [grid_top]
    for i in range(6):
        row_ys.append(row_ys[-1] + row_heights[i])

    for i, name in enumerate(WEEKDAYS):
        safe_addnstr(
            stdscr,
            y,
            col_xs[i] + 1,
            truncate(name, col_widths[i] - 2),
            col_widths[i] - 2,
            curses.color_pair(3),
        )

    for row_idx in range(6):
        for col in range(7):
            cell_x = col_xs[col]
            cell_y = row_ys[row_idx]
            cell_w = col_widths[col]
            cell_h = row_heights[row_idx]
            day = weeks[row_idx][col]
            if cell_y + cell_h > y + height:
                continue

            date = None
            if day != 0:
                date = dt.date(selected.year, selected.month, day)
            border_color = curses.color_pair(3) if date == selected else curses.color_pair(1)
            draw_box(stdscr, cell_x, cell_y, cell_w, cell_h, border_color)

            if day == 0:
                continue

            label = f"{day:2d}"
            if events_on_date(events, date):  # type: ignore[arg-type]
                label = f"{day:2d}*"
            text_color = curses.color_pair(3) if date == selected else curses.color_pair(2)
            safe_addnstr(
                stdscr,
                cell_y + 1,
                cell_x + 2,
                truncate(label, cell_w - 3),
                cell_w - 3,
                text_color,
            )


def draw_year_view(
    stdscr: curses.window,
    x: int,
    y: int,
    width: int,
    height: int,
    selected: dt.date,
) -> None:
    cols = 3
    rows = 4
    cell_base_w = max(18, width // cols)
    extra_w = max(0, width - (cell_base_w * cols))
    col_widths = [cell_base_w + (1 if i < extra_w else 0) for i in range(cols)]

    cell_base_h = max(7, height // rows)
    extra_h = max(0, height - (cell_base_h * rows))
    row_heights = [cell_base_h + (1 if i < extra_h else 0) for i in range(rows)]

    col_xs = [x]
    for i in range(cols):
        col_xs.append(col_xs[-1] + col_widths[i])
    row_ys = [y]
    for i in range(rows):
        row_ys.append(row_ys[-1] + row_heights[i])

    for month in range(1, 13):
        row = (month - 1) // cols
        col = (month - 1) % cols
        origin_x = col_xs[col]
        origin_y = row_ys[row]
        cell_w = col_widths[col]
        cell_h = row_heights[row]
        border_color = curses.color_pair(3) if month == selected.month else curses.color_pair(1)
        draw_box(stdscr, origin_x, origin_y, cell_w, cell_h, border_color)

        title = dt.date(selected.year, month, 1).strftime("%b")
        text_color = curses.color_pair(3) if month == selected.month else curses.color_pair(2)
        safe_addnstr(stdscr, origin_y + 1, origin_x + 2, truncate(title, cell_w - 3), cell_w - 3, text_color)

        weeks = calendar.monthcalendar(selected.year, month)
        max_lines = max(0, cell_h - 3)
        for week_idx, week in enumerate(weeks[:max_lines]):
            row_y = origin_y + 2 + week_idx
            day_parts = []
            for day in week:
                day_parts.append("  " if day == 0 else f"{day:2d}")
            line = " ".join(day_parts)
            safe_addnstr(
                stdscr,
                row_y,
                origin_x + 2,
                truncate(line, cell_w - 3),
                cell_w - 3,
                curses.color_pair(1),
            )


def draw_list_view(
    stdscr: curses.window,
    x: int,
    y: int,
    width: int,
    height: int,
    selected: dt.date,
    events: list[Event],
) -> None:
    month_key = selected.strftime("%Y-%m")
    header = f"Events for {month_key}"
    safe_addnstr(stdscr, y, x, truncate(header, width - 1), width - 1, curses.color_pair(3))

    def event_key(ev: Event) -> tuple[dt.date, str, str]:
        date_val = parse_date(ev.date) or dt.date.max
        time_val = "00:00" if ev.all_day else (ev.start or "99:99")
        return (date_val, time_val, ev.title.lower())

    month_events = [ev for ev in events if ev.date.startswith(month_key)]
    month_events.sort(key=event_key)

    row = y + 1
    if not month_events:
        safe_addnstr(stdscr, row, x + 1, "No events", width - 2, curses.color_pair(2))
        return

    for ev in month_events:
        if row >= y + height:
            break
        date_text = ev.date
        time_text = "All day" if ev.all_day else (ev.start or "")
        if ev.start and ev.end:
            time_text = f"{ev.start}-{ev.end}"
        label = f"{date_text}  {time_text}  {ev.title}".strip()
        color = curses.color_pair(3) if ev.date == selected.strftime("%Y-%m-%d") else curses.color_pair(2)
        safe_addnstr(stdscr, row, x + 1, truncate(label, width - 2), width - 2, color)
        row += 1


def choose_event_flow(stdscr: curses.window, events: list[Event]) -> Event | None:
    if not events:
        return None
    if len(events) == 1:
        return events[0]

    labels = [f"{idx + 1}. {event_label(ev)}" for idx, ev in enumerate(events)]
    h, w = stdscr.getmaxyx()
    max_label = max(len(label) for label in labels)
    box_w = min(w - 4, max(24, max_label + 4))
    box_h = min(h - 4, len(labels) + 2)
    box_x = max(1, (w - box_w) // 2)
    box_y = max(1, (h - box_h) // 2)
    visible_h = max(1, box_h - 2)
    selected = 0

    stdscr.timeout(-1)
    curses.flushinp()

    while True:
        draw_box(stdscr, box_x, box_y, box_w, box_h, curses.color_pair(3))
        offset = min(max(0, selected - visible_h + 1), max(0, len(labels) - visible_h))
        for i in range(visible_h):
            idx = offset + i
            if idx >= len(labels):
                break
            color = curses.color_pair(3) if idx == selected else curses.color_pair(2)
            safe_addnstr(
                stdscr,
                box_y + 1 + i,
                box_x + 2,
                truncate(labels[idx], box_w - 3),
                box_w - 3,
                color,
            )
        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            stdscr.timeout(DEFAULT_TIMEOUT)
            return None
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(labels)
            continue
        if key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(labels)
            continue
        if key in (10, 13, curses.KEY_ENTER):
            stdscr.timeout(DEFAULT_TIMEOUT)
            return events[selected]


def edit_event_flow(stdscr: curses.window, selected: dt.date, events: list[Event], state: dict) -> None:
    day_events = events_on_date(events, selected)
    if not day_events:
        set_status(state, "No events to edit on this date.")
        return
    target = choose_event_flow(stdscr, day_events)
    if target is None:
        set_status(state, "Edit cancelled.")
        return

    new_title = target.title
    new_date = target.date
    new_start = target.start
    new_end = target.end
    new_all_day = target.all_day
    new_notes = target.notes

    title_in = prompt_input(stdscr, "Title (blank keeps current):", target.title)
    if title_in:
        new_title = title_in

    date_in = prompt_input(stdscr, "Date (YYYY-MM-DD, blank keeps):", target.date)
    if date_in:
        parsed = parse_date(date_in)
        if parsed is None:
            set_status(state, "Invalid date. Edit aborted.")
            return
        new_date = parsed.strftime("%Y-%m-%d")

    start_in = prompt_input(stdscr, "Start (HH:MM, blank keeps, '-' clears):", target.start or "")
    if start_in == "-":
        new_start = None
    elif start_in:
        parsed_time = parse_time(start_in)
        if parsed_time is None:
            set_status(state, "Invalid start time. Edit aborted.")
            return
        new_start = parsed_time

    end_in = prompt_input(stdscr, "End (HH:MM, blank keeps, '-' clears):", target.end or "")
    if end_in == "-":
        new_end = None
    elif end_in:
        parsed_time = parse_time(end_in)
        if parsed_time is None:
            set_status(state, "Invalid end time. Edit aborted.")
            return
        new_end = parsed_time

    all_day_in = prompt_input(stdscr, "All-day? (y/N, blank keeps):", "y" if target.all_day else "n")
    if all_day_in:
        new_all_day = all_day_in.lower().startswith("y")

    notes_in = prompt_input(stdscr, "Notes (blank keeps, '-' clears):", target.notes or "")
    if notes_in == "-":
        new_notes = None
    elif notes_in:
        new_notes = notes_in

    if new_all_day:
        new_start = None
        new_end = None

    target.title = new_title
    target.date = new_date
    target.start = new_start
    target.end = new_end
    target.all_day = new_all_day
    target.notes = new_notes

    save_events(EVENTS_FILE, events)
    set_status(state, f"Updated event on {target.date}.")


def add_event_flow(stdscr: curses.window, selected: dt.date, events: list[Event], state: dict) -> None:
    title = prompt_input(stdscr, "Event title (blank to cancel):")
    if not title:
        set_status(state, "Add event cancelled.")
        return
    date_str = prompt_input(stdscr, "Event date (YYYY-MM-DD):", selected.strftime("%Y-%m-%d"))
    date = parse_date(date_str)
    if date is None:
        set_status(state, "Invalid date. Event not added.")
        return
    start = parse_time(prompt_input(stdscr, "Start time (HH:MM, optional):"))
    end = parse_time(prompt_input(stdscr, "End time (HH:MM, optional):"))
    all_day_input = prompt_input(stdscr, "All-day? (y/N):", "y" if not start else "n")
    all_day = all_day_input.lower().startswith("y")
    notes = prompt_input(stdscr, "Notes (optional):")

    event = Event(
        id=make_event_id(),
        title=title,
        date=date.strftime("%Y-%m-%d"),
        start=start if not all_day else None,
        end=end if not all_day else None,
        all_day=all_day,
        notes=notes or None,
    )
    events.append(event)
    save_events(EVENTS_FILE, events)
    set_status(state, f"Added event on {event.date}.")


def jump_to_date_flow(stdscr: curses.window, state: dict, selected: dt.date) -> dt.date:
    date_str = prompt_input(stdscr, "Jump to date (YYYY-MM-DD):", selected.strftime("%Y-%m-%d"))
    date = parse_date(date_str)
    if date is None:
        set_status(state, "Invalid date format.")
        return selected
    set_status(state, f"Jumped to {date.strftime('%Y-%m-%d')}.")
    return date


def move_selection(selected: dt.date, view_mode: str, key: int) -> dt.date:
    if view_mode == "year":
        if key == curses.KEY_LEFT:
            return add_months(selected, -1)
        if key == curses.KEY_RIGHT:
            return add_months(selected, 1)
        if key == curses.KEY_UP:
            return add_months(selected, -3)
        if key == curses.KEY_DOWN:
            return add_months(selected, 3)
        return selected

    if view_mode == "month":
        if key == curses.KEY_LEFT:
            return add_days(selected, -1)
        if key == curses.KEY_RIGHT:
            return add_days(selected, 1)
        if key == curses.KEY_UP:
            return add_days(selected, -7)
        if key == curses.KEY_DOWN:
            return add_days(selected, 7)
        return selected

    if key == curses.KEY_LEFT:
        return add_days(selected, -1)
    if key == curses.KEY_RIGHT:
        return add_days(selected, 1)
    if key == curses.KEY_UP:
        return add_days(selected, -7)
    if key == curses.KEY_DOWN:
        return add_days(selected, 7)
    return selected


def draw_view(
    stdscr: curses.window,
    view_mode: str,
    selected: dt.date,
    events: list[Event],
) -> None:
    h, w = stdscr.getmaxyx()
    body_top = 1
    body_bottom = h - 3
    body_h = max(1, body_bottom - body_top)

    show_side = w >= 90
    panel_w = 30 if show_side else 0
    main_w = w - panel_w - (1 if show_side else 0)

    if show_side:
        draw_events_panel(
            stdscr,
            x=main_w + 1,
            y=body_top,
            width=panel_w,
            height=body_h,
            date=selected,
            events=events_on_date(events, selected),
        )

    if view_mode == "week":
        draw_week_view(stdscr, 1, body_top, main_w - 2, body_h, selected, events)
    elif view_mode == "month":
        draw_month_view(stdscr, 1, body_top, main_w - 2, body_h, selected, events)
    elif view_mode == "list":
        draw_list_view(stdscr, 1, body_top, main_w - 2, body_h, selected, events)
    else:
        draw_year_view(stdscr, 1, body_top, main_w - 2, body_h, selected)

    if not show_side:
        panel_h = min(6, body_h)
        panel_y = body_bottom - panel_h
        if panel_y > body_top:
            draw_events_panel(
                stdscr,
                x=1,
                y=panel_y,
                width=w - 2,
                height=panel_h,
                date=selected,
                events=events_on_date(events, selected),
            )


def main(stdscr: curses.window) -> None:
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
    stdscr.timeout(DEFAULT_TIMEOUT)

    state = {"status": "Ready"}
    selected = dt.date.today()
    view_mode = "month"
    events = load_events(EVENTS_FILE)

    while True:
        stdscr.erase()
        draw_header(stdscr, view_mode, selected)
        draw_view(stdscr, view_mode, selected, events)
        draw_footer(stdscr, state["status"])
        stdscr.refresh()
        menu_bar.draw_menu_bar(root, APP_TITLE, False)
        root.refresh()

        key = stdscr.getch()
        if key == -1:
            continue

        if key in (ord("q"), ord("Q")):
            break

        if key == curses.KEY_F1:
            choice = menu_bar.open_menu(root, APP_TITLE, ROOT_DIR, THIS_FILE)
            if choice == menu_bar.EXIT_ACTION:
                break
            if isinstance(choice, Path):
                menu_bar.switch_to_app(choice)
            continue
        if key in (ord("w"), ord("W")):
            view_mode = "week"
            set_status(state, "Week view")
            continue
        if key in (ord("m"), ord("M")):
            view_mode = "month"
            set_status(state, "Month view")
            continue
        if key in (ord("y"), ord("Y")):
            view_mode = "year"
            set_status(state, "Year view")
            continue
        if key in (ord("l"), ord("L")):
            view_mode = "list"
            set_status(state, "List view")
            continue
        if key in (ord("t"), ord("T")):
            selected = dt.date.today()
            set_status(state, "Jumped to today.")
            continue
        if key in (ord("j"), ord("J")):
            selected = jump_to_date_flow(stdscr, state, selected)
            continue
        if key in (ord("a"), ord("A")):
            add_event_flow(stdscr, selected, events, state)
            continue
        if key in (ord("e"), ord("E")):
            edit_event_flow(stdscr, selected, events, state)
            continue
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_UP, curses.KEY_DOWN):
            selected = move_selection(selected, view_mode, key)
            continue


if __name__ == "__main__":
    curses.wrapper(main)
