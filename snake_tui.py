#!/usr/bin/env python3
"""Matrix-themed Snake game for TuiOS."""

from __future__ import annotations

import curses
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

APP_TITLE = "TuiOS Snake"
SCORE_FILE = Path(__file__).resolve().with_name("snake_scores.json")
MAX_SCORES = 100
TOP_DISPLAY = 12
SCORE_PER_APPLE = 10


@dataclass(frozen=True)
class Difficulty:
    name: str
    speed_ms: int
    apple_count: int


DIFFICULTIES = [
    Difficulty("Easy", 180, 6),
    Difficulty("Normal", 130, 4),
    Difficulty("Hard", 95, 3),
    Difficulty("Venom", 65, 2),
]


def center_x(width: int, text: str) -> int:
    return max(0, (width - len(text)) // 2)


def load_scores() -> list[dict]:
    if not SCORE_FILE.exists():
        return []
    try:
        data = json.loads(SCORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def save_scores(entries: list[dict]) -> None:
    payload = {"entries": entries[:MAX_SCORES]}
    SCORE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def record_score(
    entries: list[dict],
    difficulty: Difficulty,
    score: int,
    apples: int,
    length: int,
    duration: int,
) -> dict:
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "difficulty": difficulty.name,
        "score": score,
        "apples": apples,
        "length": length,
        "duration": duration,
    }
    entries.append(entry)
    entries.sort(key=lambda item: item.get("score", 0), reverse=True)
    del entries[MAX_SCORES:]
    return entry


def get_board_rect(stdscr: curses.window) -> tuple[int, int, int, int, int, int] | None:
    height, width = stdscr.getmaxyx()
    board_top = 2
    board_left = 2
    board_height = height - 4
    board_width = width - 4
    inner_h = board_height - 2
    inner_w = board_width - 2
    if inner_h < 8 or inner_w < 20:
        return None
    return board_top, board_left, board_height, board_width, inner_h, inner_w


def draw_border(
    stdscr: curses.window,
    top: int,
    left: int,
    height: int,
    width: int,
    color: int,
) -> None:
    bottom = top + height - 1
    right = left + width - 1
    stdscr.attron(curses.color_pair(color))
    stdscr.addch(top, left, curses.ACS_ULCORNER)
    stdscr.addch(top, right, curses.ACS_URCORNER)
    stdscr.addch(bottom, left, curses.ACS_LLCORNER)
    stdscr.addch(bottom, right, curses.ACS_LRCORNER)
    for x in range(left + 1, right):
        stdscr.addch(top, x, curses.ACS_HLINE)
        stdscr.addch(bottom, x, curses.ACS_HLINE)
    for y in range(top + 1, bottom):
        stdscr.addch(y, left, curses.ACS_VLINE)
        stdscr.addch(y, right, curses.ACS_VLINE)
    stdscr.attroff(curses.color_pair(color))


def draw_game(
    stdscr: curses.window,
    board: tuple[int, int, int, int, int, int],
    snake: list[tuple[int, int]],
    apples: set[tuple[int, int]],
    score: int,
    apples_eaten: int,
    difficulty: Difficulty,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    title = f"{APP_TITLE} | {difficulty.name} | Score: {score} | Apples: {apples_eaten}"
    stdscr.addnstr(0, 2, title, max(0, width - 4), curses.color_pair(2))
    stdscr.addnstr(1, 2, "Arrow keys to move. Q to end game.", max(0, width - 4), curses.color_pair(1))

    board_top, board_left, board_height, board_width, _, _ = board
    draw_border(stdscr, board_top, board_left, board_height, board_width, 1)

    for y, x in apples:
        stdscr.addch(board_top + 1 + y, board_left + 1 + x, "@", curses.color_pair(3))

    for idx, (y, x) in enumerate(snake):
        char = "O" if idx == 0 else "o"
        color = 4 if idx == 0 else 1
        stdscr.addch(board_top + 1 + y, board_left + 1 + x, char, curses.color_pair(color))

    stdscr.refresh()


def fill_apples(
    apples: set[tuple[int, int]],
    snake_cells: set[tuple[int, int]],
    target_count: int,
    inner_h: int,
    inner_w: int,
) -> None:
    if len(apples) >= target_count:
        return
    free = [
        (y, x)
        for y in range(inner_h)
        for x in range(inner_w)
        if (y, x) not in snake_cells and (y, x) not in apples
    ]
    if not free:
        return
    needed = min(target_count - len(apples), len(free))
    for pos in random.sample(free, needed):
        apples.add(pos)


def show_resize_message(stdscr: curses.window) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    lines = [
        "Terminal too small for Snake.",
        "Resize to at least 24 rows x 40 columns.",
        "Press any key to continue.",
    ]
    for idx, line in enumerate(lines):
        stdscr.addnstr(2 + idx, center_x(width, line), line, max(0, width - 2), curses.color_pair(1))
    stdscr.refresh()
    stdscr.getch()


def run_game(stdscr: curses.window, difficulty: Difficulty) -> dict | None:
    board = get_board_rect(stdscr)
    if board is None:
        show_resize_message(stdscr)
        return None

    board_top, board_left, _, _, inner_h, inner_w = board
    start_y = inner_h // 2
    start_x = inner_w // 2
    snake = [(start_y, start_x), (start_y, start_x - 1), (start_y, start_x - 2)]
    snake_cells = set(snake)
    direction = (0, 1)

    apples: set[tuple[int, int]] = set()
    fill_apples(apples, snake_cells, difficulty.apple_count, inner_h, inner_w)

    score = 0
    apples_eaten = 0
    start_time = time.monotonic()

    stdscr.timeout(difficulty.speed_ms)

    draw_game(stdscr, board, snake, apples, score, apples_eaten, difficulty)

    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return None

        if key == curses.KEY_UP:
            direction = (-1, 0) if direction != (1, 0) else direction
        elif key == curses.KEY_DOWN:
            direction = (1, 0) if direction != (-1, 0) else direction
        elif key == curses.KEY_LEFT:
            direction = (0, -1) if direction != (0, 1) else direction
        elif key == curses.KEY_RIGHT:
            direction = (0, 1) if direction != (0, -1) else direction

        head_y, head_x = snake[0]
        next_head = (head_y + direction[0], head_x + direction[1])

        if not (0 <= next_head[0] < inner_h and 0 <= next_head[1] < inner_w):
            break

        will_grow = next_head in apples
        tail = snake[-1]
        if next_head in snake_cells and not (next_head == tail and not will_grow):
            break

        snake.insert(0, next_head)
        snake_cells.add(next_head)

        if will_grow:
            apples.remove(next_head)
            apples_eaten += 1
            score += SCORE_PER_APPLE
        else:
            removed = snake.pop()
            snake_cells.discard(removed)

        fill_apples(apples, snake_cells, difficulty.apple_count, inner_h, inner_w)

        draw_game(stdscr, board, snake, apples, score, apples_eaten, difficulty)

    duration = int(time.monotonic() - start_time)
    return {
        "score": score,
        "apples": apples_eaten,
        "length": len(snake),
        "duration": duration,
    }


def draw_difficulty_menu(stdscr: curses.window, selected: int) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    stdscr.addnstr(1, center_x(width, APP_TITLE), APP_TITLE, max(0, width - 2), curses.color_pair(2))
    stdscr.addnstr(3, center_x(width, "Select Difficulty"), "Select Difficulty", max(0, width - 2), curses.color_pair(1))

    start_y = 5
    for idx, diff in enumerate(DIFFICULTIES):
        label = f"{diff.name}  | Speed {diff.speed_ms}ms  | Apples {diff.apple_count}"
        x = center_x(width, label)
        color = curses.color_pair(2) if idx == selected else curses.color_pair(1)
        marker = ">" if idx == selected else " "
        stdscr.addnstr(start_y + idx, max(0, x - 2), f"{marker} {label}", max(0, width - 4), color)

    stdscr.addnstr(height - 2, 2, "Arrow keys to choose. Enter to start. Q to quit.", max(0, width - 4), curses.color_pair(1))
    stdscr.refresh()


def select_difficulty(stdscr: curses.window) -> Difficulty | None:
    selected = 0
    stdscr.timeout(200)
    while True:
        draw_difficulty_menu(stdscr, selected)
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return None
        if key in (curses.KEY_UP,):
            selected = (selected - 1) % len(DIFFICULTIES)
        elif key in (curses.KEY_DOWN,):
            selected = (selected + 1) % len(DIFFICULTIES)
        elif key in (10, 13, curses.KEY_ENTER):
            return DIFFICULTIES[selected]


def draw_scoreboard(
    stdscr: curses.window,
    entries: list[dict],
    last_entry: dict | None,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    stdscr.addnstr(1, center_x(width, "Scoreboard"), "Scoreboard", max(0, width - 2), curses.color_pair(2))

    if last_entry is not None:
        line = (
            f"Last game: {last_entry['score']} pts, {last_entry['apples']} apples, "
            f"len {last_entry['length']}, {last_entry['duration']}s"
        )
        stdscr.addnstr(3, 2, line, max(0, width - 4), curses.color_pair(1))

    header = f"{'#':<3} {'Score':<6} {'Apples':<6} {'Len':<4} {'Diff':<8} {'When'}"
    stdscr.addnstr(5, 2, header, max(0, width - 4), curses.color_pair(2))

    sorted_entries = sorted(entries, key=lambda item: item.get("score", 0), reverse=True)
    if not sorted_entries:
        stdscr.addnstr(7, 2, "No scores yet.", max(0, width - 4), curses.color_pair(1))
    else:
        for idx, entry in enumerate(sorted_entries[:TOP_DISPLAY]):
            line = (
                f"{idx + 1:<3} {entry.get('score', 0):<6} {entry.get('apples', 0):<6} "
                f"{entry.get('length', 0):<4} {entry.get('difficulty', ''):<8} {entry.get('ts', '')}"
            )
            stdscr.addnstr(7 + idx, 2, line, max(0, width - 4), curses.color_pair(1))

    stdscr.addnstr(
        height - 2,
        2,
        "N: new game  D: change difficulty  Q: quit",
        max(0, width - 4),
        curses.color_pair(1),
    )
    stdscr.refresh()


def show_scoreboard(stdscr: curses.window, entries: list[dict], last_entry: dict | None) -> str:
    stdscr.timeout(-1)
    while True:
        draw_scoreboard(stdscr, entries, last_entry)
        key = stdscr.getch()
        if key in (ord("n"), ord("N")):
            return "new"
        if key in (ord("d"), ord("D")):
            return "difficulty"
        if key in (ord("q"), ord("Q")):
            return "quit"


def main(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    stdscr.keypad(True)

    while True:
        difficulty = select_difficulty(stdscr)
        if difficulty is None:
            return

        while True:
            result = run_game(stdscr, difficulty)
            entries = load_scores()
            last_entry = None
            if result:
                last_entry = record_score(
                    entries,
                    difficulty,
                    result["score"],
                    result["apples"],
                    result["length"],
                    result["duration"],
                )
                save_scores(entries)

            action = show_scoreboard(stdscr, entries, last_entry)
            if action == "new":
                continue
            if action == "difficulty":
                break
            if action == "quit":
                return


if __name__ == "__main__":
    curses.wrapper(main)
