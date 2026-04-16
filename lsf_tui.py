#!/usr/bin/env python3
"""
lsf_tui — Interactive terminal UI for exploring DUNE LSF mission logs.

Navigate log directories, inspect message types, preview data in tables,
and export to CSV — all from the terminal.

Understands the DUNE log directory hierarchy:
    logs/
    └── 20250325/                       ← date folder (YYYYMMDD)
        ├── 142323/                     ← session folder (HHMMSS)
        │   └── Data.lsf.gz
        ├── 143127_cmd-ntnu-autonaut/   ← session with suffix
        │   └── Data.lsf.gz
        └── ...

You can copy or symlink an entire day of logs into logs/ and the TUI
will discover and present all sessions, grouped by date.

Usage:
    python lsf_tui.py [path_to_lsf_or_directory] [--imc /path/to/IMC.xml]

Controls are shown at the bottom of each screen.
"""

import argparse
import curses
import math
import re
import sys
import time
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from imc_parser import parse_imc_xml
from lsf_reader import IMCMessage, iter_packets

DEFAULT_IMC_XML = Path(__file__).parent.parent / "dune-software" / "NEW" / "imc" / "IMC.xml"

# ── Colour pairs ──────────────────────────────────────────────────────────────
C_NORMAL   = 0
C_HEADER   = 1
C_SELECTED = 2
C_STATUS   = 3
C_TITLE    = 4
C_KEY      = 5
C_DIM      = 6
C_ACCENT   = 7
C_SUCCESS  = 8
C_DATE_HDR = 9


def init_colours():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_HEADER,   curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(C_SELECTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(C_STATUS,   curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(C_TITLE,    curses.COLOR_CYAN,  -1)
    curses.init_pair(C_KEY,      curses.COLOR_YELLOW, -1)
    curses.init_pair(C_DIM,      curses.COLOR_WHITE, -1)
    curses.init_pair(C_ACCENT,   curses.COLOR_GREEN,  -1)
    curses.init_pair(C_SUCCESS,  curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(C_DATE_HDR, curses.COLOR_YELLOW, -1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addnstr(y, x, text, max_len, attr)
    except curses.error:
        pass


def draw_header(win, title: str):
    h, w = win.getmaxyx()
    bar = " " * w
    safe_addstr(win, 0, 0, bar, curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(win, 0, 1, f" LSF Explorer  │  {title}",
                curses.color_pair(C_HEADER) | curses.A_BOLD)


def draw_statusbar(win, keys: list[tuple[str, str]]):
    h, w = win.getmaxyx()
    bar = " " * w
    safe_addstr(win, h - 1, 0, bar, curses.color_pair(C_STATUS))
    x = 1
    for key, label in keys:
        safe_addstr(win, h - 1, x, f" {key} ",
                    curses.color_pair(C_STATUS) | curses.A_BOLD)
        x += len(key) + 2
        safe_addstr(win, h - 1, x, f"{label}  ", curses.color_pair(C_STATUS))
        x += len(label) + 2


def fmt_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def fmt_timestamp(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def flatten_fields(fields: dict, prefix: str = "") -> dict:
    flat = {}
    for k, v in fields.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            flat.update(flatten_fields(v, key))
        elif isinstance(v, list):
            flat[key] = str(v)
        else:
            flat[key] = v
    return flat


def find_imc_xml(imc_arg: str = None) -> Path:
    if imc_arg:
        p = Path(imc_arg)
        if p.exists():
            return p
    candidates = [
        DEFAULT_IMC_XML,
        Path("/home/adallolio/dune-software/NEW/imc/IMC.xml"),
        Path("/home/adallolio/dune-software/NTNU/imc/IMC.xml"),
        Path("/home/adallolio/dune-software/imc/IMC.xml"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ── Log discovery and hierarchy ───────────────────────────────────────────────

RE_DATE = re.compile(r"^(\d{8})$")
RE_SESSION = re.compile(r"^(\d{6})(.*)$")


def find_lsf_files(directory: Path) -> list[Path]:
    """Recursively find all LSF files under a directory."""
    files = set()
    for pattern in ("**/Data.lsf.gz", "**/Data.lsf", "**/*.lsf.gz", "**/*.lsf"):
        files.update(directory.glob(pattern))
    return sorted(files)


def _format_date(date_str: str) -> str:
    """Format YYYYMMDD as YYYY-MM-DD."""
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _format_session_time(time_str: str) -> str:
    """Format HHMMSS as HH:MM:SS."""
    if len(time_str) >= 6 and time_str[:6].isdigit():
        return f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
    return time_str


def _parse_session_name(name: str) -> tuple[str, str]:
    """Parse a session folder name like '143127_cmd-ntnu-autonaut' into (time, suffix)."""
    m = RE_SESSION.match(name)
    if m:
        time_str = _format_session_time(m.group(1))
        suffix = m.group(2)
        if suffix.startswith("_"):
            suffix = suffix[1:]
        return time_str, suffix
    return name, ""


def build_file_tree(lsf_files: list[Path], root: Path):
    """
    Build a hierarchical view of LSF files.

    Returns a list of display entries, each being either:
        ("date_header", date_str, formatted_date, session_count)
        ("file", path, session_time, suffix, size)
        ("flat", path, rel_path, size)  — fallback for non-standard layout
    """
    date_groups = OrderedDict()
    flat_files = []

    for f in lsf_files:
        try:
            rel = f.relative_to(root)
        except ValueError:
            rel = f
        parts = rel.parts

        matched = False
        for i, part in enumerate(parts):
            if RE_DATE.match(part):
                date_str = part
                if i + 1 < len(parts) - 1:
                    session_dir = parts[i + 1]
                else:
                    session_dir = parts[i] if i + 1 == len(parts) - 1 else ""

                if date_str not in date_groups:
                    date_groups[date_str] = []
                date_groups[date_str].append((f, session_dir))
                matched = True
                break

        if not matched:
            flat_files.append((f, str(rel), f.stat().st_size))

    entries = []

    for date_str, sessions in date_groups.items():
        formatted = _format_date(date_str)
        entries.append(("date_header", date_str, formatted, len(sessions)))

        for lsf_path, session_dir in sorted(sessions, key=lambda x: x[1]):
            session_time, suffix = _parse_session_name(session_dir)
            try:
                size = lsf_path.stat().st_size
            except OSError:
                size = 0
            entries.append(("file", lsf_path, session_time, suffix, size))

    if flat_files:
        if date_groups:
            entries.append(("date_header", "", "Other logs", len(flat_files)))
        for lsf_path, rel_path, size in flat_files:
            entries.append(("flat", lsf_path, rel_path, size))

    return entries


# ── File Browser Screen ──────────────────────────────────────────────────────

def screen_file_browser(stdscr, start_path: Path) -> Path | None:
    """Browse for LSF files with DUNE log hierarchy awareness."""
    if start_path.is_file():
        return start_path

    lsf_files = find_lsf_files(start_path)
    if not lsf_files:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "No LSF files found")
        safe_addstr(stdscr, 3, 2, f"No .lsf or .lsf.gz files found under:",
                    curses.color_pair(C_DIM))
        safe_addstr(stdscr, 4, 4, str(start_path), curses.color_pair(C_ACCENT))
        safe_addstr(stdscr, 6, 2,
                    "Copy DUNE log folders (e.g. 20250325/) into this directory.",
                    curses.color_pair(C_DIM))
        safe_addstr(stdscr, 7, 2,
                    "Each date folder can contain multiple session folders",
                    curses.color_pair(C_DIM))
        safe_addstr(stdscr, 8, 2,
                    "(e.g. 142323/, 143127_cmd-ntnu-autonaut/) with Data.lsf.gz inside.",
                    curses.color_pair(C_DIM))
        draw_statusbar(stdscr, [("q", "Quit")])
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):
                return None

    entries = build_file_tree(lsf_files, start_path)

    selectable_indices = [i for i, e in enumerate(entries)
                          if e[0] in ("file", "flat")]
    if not selectable_indices:
        return None

    sel_cursor = 0
    scroll = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        total_files = len(selectable_indices)
        draw_header(stdscr, f"Select Log Session  ({total_files} logs found)")

        safe_addstr(stdscr, 2, 2, f"Directory: {start_path}",
                    curses.color_pair(C_DIM))

        visible = h - 6
        cur_entry_idx = selectable_indices[sel_cursor]

        first_visible = max(0, cur_entry_idx - visible // 2)
        if cur_entry_idx >= first_visible + visible:
            first_visible = cur_entry_idx - visible + 1
        if first_visible + visible > len(entries):
            first_visible = max(0, len(entries) - visible)

        for i in range(visible):
            eidx = first_visible + i
            if eidx >= len(entries):
                break

            entry = entries[eidx]
            y = 4 + i
            is_cur = eidx == cur_entry_idx

            if entry[0] == "date_header":
                _, date_str, formatted, count = entry
                line = f"  ┌─ {formatted}  ({count} sessions)"
                safe_addstr(stdscr, y, 1, line,
                            curses.color_pair(C_DATE_HDR) | curses.A_BOLD)

            elif entry[0] == "file":
                _, lsf_path, session_time, suffix, size = entry
                attr = (curses.color_pair(C_SELECTED) | curses.A_BOLD
                        if is_cur else 0)
                marker = "▸" if is_cur else " "
                suffix_str = f"  [{suffix}]" if suffix else ""
                size_str = fmt_size(size)
                line = f"  │ {marker} {session_time}{suffix_str}"
                safe_addstr(stdscr, y, 1, line, attr)
                safe_addstr(stdscr, y, max(1, w - 14), f"{size_str:>12}",
                            attr if is_cur else curses.color_pair(C_DIM))

            elif entry[0] == "flat":
                _, lsf_path, rel_path, size = entry
                attr = (curses.color_pair(C_SELECTED) | curses.A_BOLD
                        if is_cur else 0)
                marker = "▸" if is_cur else " "
                size_str = fmt_size(size)
                line = f"  │ {marker} {rel_path}"
                safe_addstr(stdscr, y, 1, line, attr)
                safe_addstr(stdscr, y, max(1, w - 14), f"{size_str:>12}",
                            attr if is_cur else curses.color_pair(C_DIM))

        pos_info = f"  {sel_cursor + 1}/{total_files}"
        safe_addstr(stdscr, h - 2, 1, pos_info, curses.color_pair(C_DIM))

        draw_statusbar(stdscr, [
            ("↑↓", "Navigate"), ("Enter", "Open"), ("q", "Quit"),
        ])
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and sel_cursor > 0:
            sel_cursor -= 1
        elif key == curses.KEY_DOWN and sel_cursor < total_files - 1:
            sel_cursor += 1
        elif key == curses.KEY_PPAGE:
            sel_cursor = max(0, sel_cursor - visible)
        elif key == curses.KEY_NPAGE:
            sel_cursor = min(total_files - 1, sel_cursor + visible)
        elif key == curses.KEY_HOME:
            sel_cursor = 0
        elif key == curses.KEY_END:
            sel_cursor = total_files - 1
        elif key in (curses.KEY_ENTER, 10, 13):
            eidx = selectable_indices[sel_cursor]
            entry = entries[eidx]
            return entry[1]  # lsf_path
        elif key in (ord('q'), ord('Q'), 27):
            return None


# ── Message Summary Screen ────────────────────────────────────────────────────

def load_log_summary(lsf_path: Path, msg_defs: dict):
    """Return (sorted_list_of_(abbrev, count, category), entity_map, total)."""
    counts = defaultdict(int)
    entity_map = {}
    for msg in iter_packets(lsf_path, msg_defs):
        counts[msg.abbrev] += 1
        if msg.abbrev == "EntityInfo":
            eid = msg.fields.get("id")
            label = msg.fields.get("label", "")
            if eid is not None and label:
                entity_map[eid] = label

    summary = []
    abbrev_lookup = {mdef.abbrev: mdef for mdef in msg_defs.values()}
    for abbrev, count in sorted(counts.items(), key=lambda x: -x[1]):
        mdef = abbrev_lookup.get(abbrev)
        cat = mdef.category if mdef else ""
        summary.append((abbrev, count, cat or ""))

    return summary, entity_map, sum(counts.values())


def _log_title(lsf_path: Path) -> str:
    """Build a human-readable title from the path (date / session)."""
    parts = lsf_path.parts
    date_part = ""
    session_part = ""
    for i, p in enumerate(parts):
        if RE_DATE.match(p):
            date_part = _format_date(p)
            if i + 1 < len(parts):
                next_p = parts[i + 1]
                if next_p not in (lsf_path.name,):
                    t, s = _parse_session_name(next_p)
                    session_part = t + (f" [{s}]" if s else "")
            break
    if date_part:
        title = f"{date_part}  {session_part}".strip()
    else:
        title = f"{lsf_path.parent.name}/{lsf_path.name}"
    return title


def screen_message_summary(stdscr, lsf_path: Path, msg_defs: dict):
    """Show message type summary. Returns selected abbrev or action."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Loading...")
    safe_addstr(stdscr, h // 2, w // 2 - 10, "Reading LSF file...",
                curses.color_pair(C_ACCENT) | curses.A_BOLD)
    stdscr.refresh()

    t0 = time.monotonic()
    summary, entity_map, total = load_log_summary(lsf_path, msg_defs)
    load_time = time.monotonic() - t0

    cursor = 0
    scroll = 0
    selected = set()
    title = _log_title(lsf_path)

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        draw_header(stdscr, title)

        info = (f"  {total:,} messages  │  {len(summary)} types  │  "
                f"Loaded in {load_time:.1f}s")
        safe_addstr(stdscr, 2, 0, info, curses.color_pair(C_DIM))

        col_hdr = f"  {'':3}  {'Message Type':<30} {'Category':<22} {'Count':>10}"
        safe_addstr(stdscr, 4, 0, col_hdr,
                    curses.color_pair(C_TITLE) | curses.A_BOLD)
        safe_addstr(stdscr, 5, 0, "─" * min(w - 1, 75), curses.color_pair(C_DIM))

        visible = h - 9
        if cursor < scroll:
            scroll = cursor
        if cursor >= scroll + visible:
            scroll = cursor - visible + 1

        for i in range(visible):
            idx = scroll + i
            if idx >= len(summary):
                break
            abbrev, count, cat = summary[idx]
            y = 6 + i
            is_cur = idx == cursor
            is_sel = abbrev in selected

            attr = curses.color_pair(C_SELECTED) | curses.A_BOLD if is_cur else 0
            check = "[x]" if is_sel else "[ ]"
            marker = "▸" if is_cur else " "
            line = f"  {marker}{check} {abbrev:<30} {cat:<22} {count:>10}"
            safe_addstr(stdscr, y, 0, line, attr)

        sel_info = f"  {len(selected)} selected" if selected else ""
        safe_addstr(stdscr, h - 2, 1, sel_info,
                    curses.color_pair(C_ACCENT))

        keys = [
            ("↑↓", "Navigate"), ("Space", "Select"), ("Enter", "View"),
            ("e", "Export CSV"), ("a", "Select All"), ("b", "Back"), ("q", "Quit"),
        ]
        draw_statusbar(stdscr, keys)
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and cursor > 0:
            cursor -= 1
        elif key == curses.KEY_DOWN and cursor < len(summary) - 1:
            cursor += 1
        elif key == curses.KEY_PPAGE:
            cursor = max(0, cursor - visible)
        elif key == curses.KEY_NPAGE:
            cursor = min(len(summary) - 1, cursor + visible)
        elif key == curses.KEY_HOME:
            cursor = 0
        elif key == curses.KEY_END:
            cursor = len(summary) - 1
        elif key == ord(' '):
            abbrev = summary[cursor][0]
            if abbrev in selected:
                selected.discard(abbrev)
            else:
                selected.add(abbrev)
        elif key == ord('a') or key == ord('A'):
            if len(selected) == len(summary):
                selected.clear()
            else:
                selected = {s[0] for s in summary}
        elif key in (curses.KEY_ENTER, 10, 13):
            abbrev = summary[cursor][0]
            return ("view", abbrev, entity_map)
        elif key == ord('e') or key == ord('E'):
            to_export = selected if selected else {summary[cursor][0]}
            return ("export", to_export, entity_map)
        elif key == ord('b') or key == ord('B'):
            return ("back", None, entity_map)
        elif key in (ord('q'), ord('Q'), 27):
            return ("quit", None, entity_map)


# ── Message Data Viewer ──────────────────────────────────────────────────────

LAT_LON_FIELDS = {"lat", "lon"}


def load_messages(lsf_path: Path, msg_defs: dict, abbrev: str,
                  entity_map: dict) -> tuple[list[str], list[list[str]]]:
    """Load messages and return (columns, rows) for table display."""
    messages = list(iter_packets(lsf_path, msg_defs, {abbrev}))

    all_field_keys = []
    field_key_set = set()
    all_flat = []

    for msg in messages:
        flat = flatten_fields(msg.fields)
        for k in LAT_LON_FIELDS:
            if k in flat and isinstance(flat[k], (int, float)):
                flat[k] = math.degrees(flat[k])
        for k in flat:
            if k not in field_key_set:
                field_key_set.add(k)
                all_field_keys.append(k)
        all_flat.append((msg, flat))

    columns = ["timestamp", "src_entity"] + all_field_keys
    rows = []
    for msg, flat in all_flat:
        row = [
            fmt_timestamp(msg.header.timestamp),
            entity_map.get(msg.header.src_ent, str(msg.header.src_ent)),
        ]
        for k in all_field_keys:
            val = flat.get(k, "")
            if isinstance(val, float):
                if abs(val) > 1e-6 or val == 0:
                    val = f"{val:.6f}"
                else:
                    val = f"{val:.2e}"
            row.append(str(val))
        rows.append(row)

    return columns, rows


def screen_data_viewer(stdscr, lsf_path: Path, msg_defs: dict,
                       abbrev: str, entity_map: dict):
    """Interactive table view of a single message type."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Loading...")
    safe_addstr(stdscr, h // 2, w // 2 - 10, f"Loading {abbrev}...",
                curses.color_pair(C_ACCENT) | curses.A_BOLD)
    stdscr.refresh()

    columns, rows = load_messages(lsf_path, msg_defs, abbrev, entity_map)
    if not rows:
        stdscr.erase()
        draw_header(stdscr, abbrev)
        safe_addstr(stdscr, h // 2, w // 2 - 10, "No data found.",
                    curses.color_pair(C_DIM))
        stdscr.getch()
        return

    col_widths = []
    for i, col in enumerate(columns):
        max_w = len(col)
        for row in rows[:200]:
            if i < len(row):
                max_w = max(max_w, len(row[i]))
        col_widths.append(min(max_w, 30))

    row_cursor = 0
    col_scroll = 0
    row_scroll = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        draw_header(stdscr, f"{abbrev}  ({len(rows):,} messages)")

        hdr_y = 2
        x = 1
        for ci in range(col_scroll, len(columns)):
            if x >= w - 1:
                break
            cw = col_widths[ci]
            text = columns[ci][:cw].ljust(cw)
            safe_addstr(stdscr, hdr_y, x, text,
                        curses.color_pair(C_TITLE) | curses.A_BOLD)
            x += cw + 2
        safe_addstr(stdscr, hdr_y + 1, 1, "─" * (w - 2),
                    curses.color_pair(C_DIM))

        visible_rows = h - 7
        if row_cursor < row_scroll:
            row_scroll = row_cursor
        if row_cursor >= row_scroll + visible_rows:
            row_scroll = row_cursor - visible_rows + 1

        for ri in range(visible_rows):
            idx = row_scroll + ri
            if idx >= len(rows):
                break
            y = hdr_y + 2 + ri
            is_cur = idx == row_cursor
            attr = curses.color_pair(C_SELECTED) if is_cur else 0

            x = 1
            for ci in range(col_scroll, len(columns)):
                if x >= w - 1:
                    break
                cw = col_widths[ci]
                val = rows[idx][ci] if ci < len(rows[idx]) else ""
                text = val[:cw].ljust(cw)
                safe_addstr(stdscr, y, x, text, attr)
                x += cw + 2

        pct = int(100 * (row_cursor + 1) / len(rows)) if rows else 0
        pos_info = f"  Row {row_cursor + 1}/{len(rows)} ({pct}%)"
        safe_addstr(stdscr, h - 2, 1, pos_info, curses.color_pair(C_DIM))

        col_info = (f"  Col {col_scroll + 1}-"
                    f"{min(col_scroll + 10, len(columns))}/{len(columns)}")
        safe_addstr(stdscr, h - 2, 35, col_info, curses.color_pair(C_DIM))

        keys = [
            ("↑↓", "Rows"), ("←→", "Cols"), ("PgUp/Dn", "Page"),
            ("d", "Detail"), ("b", "Back"), ("q", "Quit"),
        ]
        draw_statusbar(stdscr, keys)
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and row_cursor > 0:
            row_cursor -= 1
        elif key == curses.KEY_DOWN and row_cursor < len(rows) - 1:
            row_cursor += 1
        elif key == curses.KEY_LEFT and col_scroll > 0:
            col_scroll -= 1
        elif key == curses.KEY_RIGHT and col_scroll < len(columns) - 1:
            col_scroll += 1
        elif key == curses.KEY_PPAGE:
            row_cursor = max(0, row_cursor - visible_rows)
        elif key == curses.KEY_NPAGE:
            row_cursor = min(len(rows) - 1, row_cursor + visible_rows)
        elif key == curses.KEY_HOME:
            row_cursor = 0
        elif key == curses.KEY_END:
            row_cursor = len(rows) - 1
        elif key == ord('d') or key == ord('D'):
            screen_detail_view(stdscr, columns, rows[row_cursor], abbrev,
                               row_cursor)
        elif key == ord('b') or key == ord('B'):
            return
        elif key in (ord('q'), ord('Q'), 27):
            raise SystemExit(0)


# ── Single Message Detail View ────────────────────────────────────────────────

def screen_detail_view(stdscr, columns: list[str], row: list[str],
                       abbrev: str, row_idx: int):
    """Vertical field-by-field view of a single message."""
    cursor = 0
    scroll = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        draw_header(stdscr, f"{abbrev}  │  Message #{row_idx + 1}")

        visible = h - 5
        if cursor < scroll:
            scroll = cursor
        if cursor >= scroll + visible:
            scroll = cursor - visible + 1

        for i in range(visible):
            idx = scroll + i
            if idx >= len(columns):
                break
            y = 2 + i
            is_cur = idx == cursor
            attr = curses.color_pair(C_SELECTED) if is_cur else 0

            field_name = columns[idx]
            value = row[idx] if idx < len(row) else ""
            safe_addstr(stdscr, y, 2, f"{field_name:<25}", attr | curses.A_BOLD)
            safe_addstr(stdscr, y, 28, f"│ {value}", attr)

        draw_statusbar(stdscr, [
            ("↑↓", "Navigate"), ("b/Esc", "Back"),
        ])
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and cursor > 0:
            cursor -= 1
        elif key == curses.KEY_DOWN and cursor < len(columns) - 1:
            cursor += 1
        elif key == curses.KEY_PPAGE:
            cursor = max(0, cursor - visible)
        elif key == curses.KEY_NPAGE:
            cursor = min(len(columns) - 1, cursor + visible)
        elif key in (ord('b'), ord('B'), 27):
            return


# ── CSV Export Screen ─────────────────────────────────────────────────────────

def screen_export(stdscr, lsf_path: Path, msg_defs: dict,
                  abbrevs: set, entity_map: dict):
    """Export selected message types to CSV with a progress display."""
    import csv

    out_dir = lsf_path.parent / "csv_export"
    out_dir.mkdir(parents=True, exist_ok=True)

    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Exporting to CSV...")

    results = []
    for i, abbrev in enumerate(sorted(abbrevs)):
        safe_addstr(stdscr, 3 + i, 2,
                    f"  Exporting {abbrev}...",
                    curses.color_pair(C_DIM))
        stdscr.refresh()

        columns, rows = load_messages(lsf_path, msg_defs, abbrev, entity_map)
        if not rows:
            results.append((abbrev, 0, "no data"))
            continue

        out_path = out_dir / f"{abbrev}.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

        results.append((abbrev, len(rows), str(out_path)))

        safe_addstr(stdscr, 3 + i, 2,
                    f"  ✓ {abbrev:<25} {len(rows):>8} rows  → {out_path}",
                    curses.color_pair(C_ACCENT))
        stdscr.refresh()

    y_done = 3 + len(results) + 1
    total_rows = sum(r[1] for r in results)
    safe_addstr(stdscr, y_done, 2,
                f"Export complete: {total_rows:,} rows total to {out_dir}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)

    draw_statusbar(stdscr, [("Enter/b", "Back")])
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord('b'), ord('B'), 27):
            return


# ── Main Application Loop ────────────────────────────────────────────────────

def app_main(stdscr, start_path: Path, msg_defs: dict):
    curses.curs_set(0)
    init_colours()
    stdscr.keypad(True)

    lsf_path = screen_file_browser(stdscr, start_path)
    if lsf_path is None:
        return

    while True:
        result = screen_message_summary(stdscr, lsf_path, msg_defs)
        action, data, entity_map = result

        if action == "quit":
            return
        elif action == "back":
            new_path = screen_file_browser(stdscr, start_path)
            if new_path is None:
                return
            lsf_path = new_path
        elif action == "view":
            screen_data_viewer(stdscr, lsf_path, msg_defs, data, entity_map)
        elif action == "export":
            screen_export(stdscr, lsf_path, msg_defs, data, entity_map)


def main():
    parser = argparse.ArgumentParser(
        description="Interactive terminal UI for DUNE LSF mission logs.",
    )
    parser.add_argument("path", type=Path, nargs="?",
                        default=Path(__file__).parent / "logs",
                        help="LSF file or directory to browse (default: ./logs)")
    parser.add_argument("--imc", type=str, default=None,
                        help="Path to IMC.xml definitions file")
    args = parser.parse_args()

    imc_xml = find_imc_xml(args.imc)
    if imc_xml is None:
        print("Error: Could not find IMC.xml. Use --imc to specify the path.",
              file=sys.stderr)
        sys.exit(1)

    msg_defs = parse_imc_xml(str(imc_xml))
    start_path = args.path.resolve()

    if not start_path.exists():
        print(f"Path not found: {start_path}", file=sys.stderr)
        print("Copy DUNE log folders (e.g. 20250325/) into logs/ and try again.",
              file=sys.stderr)
        sys.exit(1)

    try:
        curses.wrapper(app_main, start_path, msg_defs)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
