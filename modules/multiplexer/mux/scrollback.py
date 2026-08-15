"""
Scrollback buffer.

Each pane maintains a ring buffer of terminal output lines.  The user can
scroll back through this history without affecting the live terminal content.

Copy mode places a cursor in the scrollback buffer; pressing Enter or y
copies the selection to the copy buffer.

Lines are stored as raw byte strings (not decoded) to avoid losing escape
sequences when they are sent back to the terminal.
"""

from __future__ import annotations

from collections import deque

from mux.config import SCROLLBACK


class ScrollbackBuffer:
    """
    A fixed-capacity deque of byte strings (terminal output lines).

    scroll_pos = 0  → viewing the live bottom of the buffer
    scroll_pos = n  → scrolled n lines back from the bottom
    """

    def __init__(self, capacity: int = SCROLLBACK):
        self._capacity  = capacity
        self._lines: deque[bytes] = deque(maxlen=capacity)
        self._scroll_pos: int = 0

        # Copy mode state
        self._copy_mode:   bool = False
        self._cursor_row:  int  = 0   # row within visible area
        self._cursor_col:  int  = 0
        self._select_start: tuple[int, int] | None = None
        self._copy_buffer:  bytes = b""

    # ── Line management ───────────────────────────────────────────────────

    def append(self, line: bytes):
        """Add a line to the end of the buffer."""
        self._lines.append(line)

    def append_chunk(self, data: bytes):
        """Split raw terminal output by newlines and append each line."""
        for part in data.split(b"\n"):
            self._lines.append(part)

    def __len__(self) -> int:
        return len(self._lines)

    def visible_lines(self, n: int) -> list[bytes]:
        """
        Return the n lines that should be visible at the current scroll position.
        scroll_pos=0 shows the newest n lines; scroll_pos=k shifts k lines back.
        """
        total = len(self._lines)
        end   = max(0, total - self._scroll_pos)
        start = max(0, end - n)
        lines = list(self._lines)[start:end]
        # Pad to n lines if buffer is short
        while len(lines) < n:
            lines.insert(0, b"")
        return lines

    # ── Scroll operations ─────────────────────────────────────────────────

    def scroll_up(self, n: int = 1):
        max_scroll = max(0, len(self._lines) - 1)
        self._scroll_pos = min(self._scroll_pos + n, max_scroll)

    def scroll_down(self, n: int = 1):
        self._scroll_pos = max(0, self._scroll_pos - n)

    def scroll_to_bottom(self):
        self._scroll_pos = 0

    @property
    def at_bottom(self) -> bool:
        return self._scroll_pos == 0

    @property
    def scroll_pos(self) -> int:
        return self._scroll_pos

    # ── Copy mode ─────────────────────────────────────────────────────────

    def enter_copy_mode(self):
        self._copy_mode    = True
        self._cursor_row   = 0
        self._cursor_col   = 0
        self._select_start = None

    def exit_copy_mode(self):
        self._copy_mode    = False
        self._select_start = None

    @property
    def in_copy_mode(self) -> bool:
        return self._copy_mode

    def cursor_move(self, dr: int, dc: int, visible_rows: int, visible_cols: int):
        self._cursor_row = max(0, min(self._cursor_row + dr, visible_rows - 1))
        self._cursor_col = max(0, min(self._cursor_col + dc, visible_cols - 1))

    def start_selection(self):
        self._select_start = (self._cursor_row, self._cursor_col)

    def copy_selection(self, visible_lines: list[bytes]) -> bytes:
        """Copy the selected range to the internal copy buffer."""
        if self._select_start is None:
            # Copy the current cursor line
            if 0 <= self._cursor_row < len(visible_lines):
                self._copy_buffer = visible_lines[self._cursor_row]
            return self._copy_buffer

        r0, c0 = self._select_start
        r1, c1 = self._cursor_row, self._cursor_col
        if (r0, c0) > (r1, c1):
            r0, c0, r1, c1 = r1, c1, r0, c0

        chunks = []
        for row in range(r0, min(r1 + 1, len(visible_lines))):
            line = visible_lines[row]
            if row == r0 == r1:
                chunks.append(line[c0:c1 + 1])
            elif row == r0:
                chunks.append(line[c0:])
            elif row == r1:
                chunks.append(line[:c1 + 1])
            else:
                chunks.append(line)

        self._copy_buffer  = b"\n".join(chunks)
        self._select_start = None
        return self._copy_buffer

    @property
    def copy_buffer(self) -> bytes:
        return self._copy_buffer

    @property
    def cursor(self) -> tuple[int, int]:
        return self._cursor_row, self._cursor_col
