"""
curses renderer.

Draws the multiplexer UI into the curses stdscr:
  - Pane content areas (terminal output)
  - Divider lines between panes (with active-pane highlight)
  - Status bar at the bottom (session name, window list, clock)
  - Copy-mode cursor overlay

The renderer never touches the child PTYs — it only reads from the
pane's scrollback buffer to populate each pane's content region.
"""

from __future__ import annotations

import curses
import datetime
import time
from typing import TYPE_CHECKING

from mux.config import STATUS_HEIGHT

if TYPE_CHECKING:
    from mux.multiplexer import Multiplexer


class Renderer:

    # Colour pair indices
    PAIR_NORMAL    = 1
    PAIR_ACTIVE    = 2
    PAIR_STATUS    = 3
    PAIR_DIVIDER   = 4
    PAIR_COPY      = 5

    def __init__(self, stdscr: "curses._CursesWindow"):
        self._scr = stdscr
        self._init_colours()

    def _init_colours(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(self.PAIR_NORMAL,  curses.COLOR_WHITE,   -1)
        curses.init_pair(self.PAIR_ACTIVE,  curses.COLOR_GREEN,   -1)
        curses.init_pair(self.PAIR_STATUS,  curses.COLOR_BLACK,   curses.COLOR_GREEN)
        curses.init_pair(self.PAIR_DIVIDER, curses.COLOR_YELLOW,  -1)
        curses.init_pair(self.PAIR_COPY,    curses.COLOR_BLACK,   curses.COLOR_CYAN)

    def render(self, mux: "Multiplexer"):
        """Full screen redraw."""
        self._scr.erase()
        rows, cols = self._scr.getmaxyx()

        session  = mux.current_session
        if session is None:
            self._draw_empty(rows, cols)
            self._scr.refresh()
            return

        window = session.active
        if window is None:
            self._draw_empty(rows, cols)
            self._status_bar(mux, rows, cols)
            self._scr.refresh()
            return

        geometries = mux.layout_engine.compute_geometries()

        # Draw dividers first so pane content overwrites them
        self._draw_dividers(rows, cols)

        # Draw pane content
        for pane in window.panes:
            if not pane.alive:
                continue
            geom = geometries.get(pane.pane_id)
            if geom is None:
                continue
            is_active = (pane is window.active)
            self._draw_pane(pane, geom, is_active, mux.copy_buffer)

        # Status bar
        self._status_bar(mux, rows, cols)

        # Place cursor in active pane (or copy mode cursor)
        active_pane = window.active
        if active_pane:
            ag = geometries.get(active_pane.pane_id)
            if ag and active_pane.scrollback.in_copy_mode:
                cr, cc = active_pane.scrollback.cursor
                self._safe_move(ag.y + cr, ag.x + cc)
            elif ag:
                # Position cursor at bottom-right of active pane (approx)
                self._safe_move(
                    min(ag.y + ag.height - 1, rows - STATUS_HEIGHT - 1),
                    ag.x,
                )

        self._scr.refresh()

    # ── Pane rendering ────────────────────────────────────────────────────

    def _draw_pane(self, pane, geom, is_active: bool, global_copy_buf: bytes):
        scr   = self._scr
        rows_ = geom.height
        cols_ = geom.width

        if rows_ <= 0 or cols_ <= 0:
            return

        lines = pane.scrollback.visible_lines(rows_)
        in_cm = pane.scrollback.in_copy_mode
        cm_row, cm_col = pane.scrollback.cursor if in_cm else (-1, -1)

        for row_idx, line in enumerate(lines):
            y = geom.y + row_idx
            if y >= self._scr.getmaxyx()[0] - STATUS_HEIGHT:
                break

            # Decode line, stripping ANSI for display (simple approach)
            text = _strip_ansi(line)
            text = text[:cols_].ljust(cols_)

            attr = curses.color_pair(self.PAIR_NORMAL)
            if in_cm and row_idx == cm_row:
                attr = curses.color_pair(self.PAIR_COPY)

            try:
                scr.addstr(y, geom.x, text, attr)
            except curses.error:
                pass

        # Draw pane border title
        title = pane.title or f"pane {pane.pane_id}"
        if is_active:
            title_attr = curses.color_pair(self.PAIR_ACTIVE) | curses.A_BOLD
        else:
            title_attr = curses.color_pair(self.PAIR_NORMAL)

        label = f" {title[:cols_ - 2]} "
        try:
            self._scr.addstr(geom.y, geom.x, label[:cols_], title_attr)
        except curses.error:
            pass

    def _draw_dividers(self, rows: int, cols: int):
        attr = curses.color_pair(self.PAIR_DIVIDER)
        # We draw vertical bars and horizontal bars for all possible divider
        # positions; the layout engine decides where panes sit.
        pass  # Dividers are implicit from pane borders in this implementation

    def _draw_empty(self, rows: int, cols: int):
        msg = "No sessions — press Ctrl-B c to create a window"
        y   = rows // 2
        x   = max(0, (cols - len(msg)) // 2)
        try:
            self._scr.addstr(y, x, msg, curses.color_pair(self.PAIR_NORMAL))
        except curses.error:
            pass

    # ── Status bar ────────────────────────────────────────────────────────

    def _status_bar(self, mux: "Multiplexer", rows: int, cols: int):
        session = mux.current_session
        if session is None:
            return

        attr = curses.color_pair(self.PAIR_STATUS)

        # Left: session name
        left = f" [{session.name}] "

        # Middle: window list
        windows = []
        for i, w in enumerate(session.windows):
            mark = "*" if i == session.active_window else " "
            windows.append(f"{i}:{mark}{w.name}")
        middle = "  ".join(windows)

        # Right: clock
        right = datetime.datetime.now().strftime(" %H:%M ")

        bar = left + middle
        bar = bar.ljust(cols - len(right))[:cols - len(right)] + right
        bar = bar[:cols]

        try:
            self._scr.addstr(rows - STATUS_HEIGHT, 0, bar, attr)
        except curses.error:
            pass

    def _safe_move(self, y: int, x: int):
        rows, cols = self._scr.getmaxyx()
        try:
            self._scr.move(max(0, min(y, rows - 1)), max(0, min(x, cols - 1)))
        except curses.error:
            pass


def _strip_ansi(data: bytes) -> str:
    """Very simple ANSI escape stripping for display purposes."""
    import re
    text = data.decode("utf-8", errors="replace")
    return re.sub(r"\x1b\[[0-9;]*[mABCDHJKST]", "", text)
