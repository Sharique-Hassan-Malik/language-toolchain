"""
Core multiplexer.

The Multiplexer class owns:
  - A list of SessionState objects
  - One LayoutEngine per window (keyed by window_id)
  - One PtyProcess per pane (keyed by pane_id)
  - One ScrollbackBuffer per pane (keyed by pane_id)

The main event loop:
  1. select() on all live pty master fds + stdin
  2. For each readable pty fd: read data → append to scrollback → schedule redraw
  3. For stdin: read key → if prefix seen, dispatch to command; else forward to active pane
  4. Redraw when dirty (at most once per 10 ms to avoid tearing)
"""

from __future__ import annotations

import curses
import os
import select
import signal
import sys
import time
from typing import Callable

from mux.config import (
    MuxConfig, PaneState, WindowState, SessionState,
    BINDINGS, PREFIX_KEY, PaneGeometry, STATUS_HEIGHT,
)
from mux.layout import LayoutEngine, SplitDir
from mux.pty_proc import PtyProcess, get_terminal_size
from mux.scrollback import ScrollbackBuffer
from mux.renderer import Renderer


class Multiplexer:

    def __init__(self, config: MuxConfig | None = None):
        self._config    = config or MuxConfig()
        self._sessions: list[SessionState]          = []
        self._session_idx: int                      = 0
        self._layouts:  dict[int, LayoutEngine]     = {}   # window_id → layout
        self._ptys:     dict[int, PtyProcess]       = {}   # pane_id   → pty
        self._scrollbacks: dict[int, ScrollbackBuffer] = {}
        self._copy_buffer: bytes                    = b""

        self._running     = False
        self._dirty       = True
        self._prefix_seen = False
        self._renderer:   Renderer | None = None

        # IDs
        self._next_session = 0
        self._next_window  = 0
        self._next_pane    = 0

    # ── Public helpers accessed by renderer ──────────────────────────────

    @property
    def current_session(self) -> SessionState | None:
        if not self._sessions:
            return None
        return self._sessions[self._session_idx % len(self._sessions)]

    @property
    def layout_engine(self) -> LayoutEngine | None:
        session = self.current_session
        if session is None or session.active is None:
            return None
        return self._layouts.get(session.active.window_id)

    @property
    def copy_buffer(self) -> bytes:
        return self._copy_buffer

    # ── Entry point ───────────────────────────────────────────────────────

    def run(self):
        """Start the multiplexer inside curses."""
        curses.wrapper(self._main)

    def _main(self, stdscr: "curses._CursesWindow"):
        curses.cbreak()
        curses.noecho()
        stdscr.keypad(True)
        stdscr.nodelay(True)
        curses.curs_set(1)

        self._renderer = Renderer(stdscr)
        rows, cols     = stdscr.getmaxyx()

        # Create the initial session, window and pane
        self._new_session("main", rows, cols)

        self._running = True
        last_draw = 0.0

        signal.signal(signal.SIGWINCH, self._handle_sigwinch)

        while self._running:
            now = time.monotonic()
            if self._dirty and now - last_draw > 0.01:
                self._renderer.render(self)
                last_draw = now
                self._dirty = False

            # Build fd set: stdin + all live pty masters
            read_fds = [sys.stdin.fileno()]
            fd_to_pane: dict[int, int] = {}
            for pane_id, pty_proc in list(self._ptys.items()):
                if pty_proc.alive:
                    fd = pty_proc.fileno()
                    read_fds.append(fd)
                    fd_to_pane[fd] = pane_id
                else:
                    self._pane_died(pane_id)

            try:
                r, _, _ = select.select(read_fds, [], [], 0.05)
            except (select.error, ValueError):
                continue

            for fd in r:
                if fd == sys.stdin.fileno():
                    self._handle_input(stdscr)
                elif fd in fd_to_pane:
                    self._read_pane(fd_to_pane[fd])

    # ── Session / window / pane creation ─────────────────────────────────

    def _new_session(self, name: str, rows: int, cols: int) -> SessionState:
        sid     = self._next_session
        self._next_session += 1
        session = SessionState(session_id=sid, name=name)
        self._sessions.append(session)
        self._session_idx = len(self._sessions) - 1
        self._new_window(session, "bash", rows, cols)
        return session

    def _new_window(
        self, session: SessionState, name: str, rows: int, cols: int
    ) -> WindowState:
        wid    = self._next_window
        self._next_window += 1
        window = WindowState(window_id=wid, name=name)
        session.windows.append(window)
        session.active_window = len(session.windows) - 1

        engine = LayoutEngine(rows, cols)
        self._layouts[wid] = engine

        self._new_pane(window, engine, rows, cols, cwd=None)
        return window

    def _new_pane(
        self,
        window: WindowState,
        engine: LayoutEngine,
        rows: int, cols: int,
        cwd: str | None,
    ) -> PaneState:
        pane_id = engine.add_initial() if not window.panes else self._next_pane
        if window.panes:
            # Split the active pane
            active_id = window.active.pane_id if window.active else 0
            new_id    = engine.split(active_id, SplitDir.VERTICAL)
            if new_id is None:
                new_id = engine.split(active_id, SplitDir.HORIZONTAL)
            if new_id is not None:
                pane_id = new_id

        self._next_pane = max(self._next_pane, pane_id + 1)
        geometries = engine.compute_geometries()
        geom = geometries.get(pane_id, PaneGeometry(0, 0, cols, rows - STATUS_HEIGHT))

        pty_proc = PtyProcess.spawn(
            shell=self._config.shell,
            rows=geom.height,
            cols=geom.width,
            cwd=cwd,
        )
        sb = ScrollbackBuffer(self._config.history_limit)

        pane = PaneState(
            pane_id=pane_id,
            geometry=geom,
            pid=pty_proc.pid,
            fd=pty_proc.master_fd,
        )
        window.panes.append(pane)
        window.active_pane = len(window.panes) - 1

        self._ptys[pane_id]       = pty_proc
        self._scrollbacks[pane_id] = sb
        return pane

    # ── I/O ──────────────────────────────────────────────────────────────

    def _read_pane(self, pane_id: int):
        pty_proc = self._ptys.get(pane_id)
        sb       = self._scrollbacks.get(pane_id)
        if pty_proc is None or sb is None:
            return
        data = pty_proc.read(4096)
        if data:
            sb.append_chunk(data)
            self._dirty = True

    def _pane_died(self, pane_id: int):
        session = self.current_session
        if session is None:
            return
        window  = session.active
        if window is None:
            return
        pane = next((p for p in window.panes if p.pane_id == pane_id), None)
        if pane:
            pane.alive = False
        self._dirty = True

    # ── Key handling ─────────────────────────────────────────────────────

    def _handle_input(self, stdscr: "curses._CursesWindow"):
        try:
            key = stdscr.getkey()
        except curses.error:
            return

        if self._prefix_seen:
            self._prefix_seen = False
            self._dispatch_command(key)
        elif key == PREFIX_KEY:
            self._prefix_seen = True
        else:
            self._forward_to_active_pane(key.encode("utf-8", errors="replace"))

    def _dispatch_command(self, key: str):
        cmd = BINDINGS.get(key)
        if cmd is None:
            return
        getattr(self, f"_cmd_{cmd}", lambda: None)()
        self._dirty = True

    def _forward_to_active_pane(self, data: bytes):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        pane = window.active
        if pane is None or not pane.alive:
            return
        pty_proc = self._ptys.get(pane.pane_id)
        if pty_proc:
            pty_proc.write(data)

    # ── Commands ──────────────────────────────────────────────────────────

    def _cmd_split_vertical(self):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        engine = self._layouts.get(window.window_id)
        if engine is None:
            return
        rows, cols = get_terminal_size()
        self._new_pane(window, engine, rows, cols, cwd=None)

    def _cmd_split_horizontal(self):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        engine = self._layouts.get(window.window_id)
        if engine is None:
            return
        active = window.active
        if active and engine:
            engine.split(active.pane_id, SplitDir.HORIZONTAL)
            rows, cols = get_terminal_size()
            self._new_pane(window, engine, rows, cols, cwd=None)

    def _cmd_kill_pane(self):
        session = self.current_session
        if session is None:
            return
        window  = session.active
        if window is None:
            return
        pane    = window.active
        if pane is None:
            return
        pty = self._ptys.pop(pane.pane_id, None)
        if pty:
            pty.kill()
        engine = self._layouts.get(window.window_id)
        if engine:
            engine.remove(pane.pane_id)
        window.panes = [p for p in window.panes if p.pane_id != pane.pane_id]
        if window.active_pane >= len(window.panes) and window.panes:
            window.active_pane = len(window.panes) - 1
        if not window.panes:
            self._cmd_kill_window()

    def _cmd_kill_window(self):
        session = self.current_session
        if session is None:
            return
        w_idx = session.active_window
        session.windows.pop(w_idx)
        if not session.windows:
            self._running = False
            return
        session.active_window = min(w_idx, len(session.windows) - 1)

    def _cmd_new_window(self):
        session = self.current_session
        if session is None:
            return
        rows, cols = get_terminal_size()
        self._new_window(session, "bash", rows, cols)

    def _cmd_next_window(self):
        session = self.current_session
        if session and session.windows:
            session.active_window = (session.active_window + 1) % len(session.windows)

    def _cmd_prev_window(self):
        session = self.current_session
        if session and session.windows:
            session.active_window = (session.active_window - 1) % len(session.windows)

    def _cmd_focus_left(self):   self._focus_move(SplitDir.HORIZONTAL, prefer_second=False)
    def _cmd_focus_right(self):  self._focus_move(SplitDir.HORIZONTAL, prefer_second=True)
    def _cmd_focus_up(self):     self._focus_move(SplitDir.VERTICAL,   prefer_second=False)
    def _cmd_focus_down(self):   self._focus_move(SplitDir.VERTICAL,   prefer_second=True)

    def _focus_move(self, direction: SplitDir, prefer_second: bool):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        engine  = self._layouts.get(window.window_id)
        active  = window.active
        if engine is None or active is None:
            return
        neighbour = engine.neighbour(active.pane_id, direction, prefer_second)
        if neighbour is not None:
            idx = next(
                (i for i, p in enumerate(window.panes) if p.pane_id == neighbour),
                None,
            )
            if idx is not None:
                window.active_pane = idx

    def _cmd_enter_copy_mode(self):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        pane = window.active
        if pane is None:
            return
        sb = self._scrollbacks.get(pane.pane_id)
        if sb:
            sb.enter_copy_mode()

    def _cmd_paste_buffer(self):
        session = self.current_session
        if session is None:
            return
        window = session.active
        if window is None:
            return
        pane = window.active
        if pane and self._copy_buffer:
            pty = self._ptys.get(pane.pane_id)
            if pty:
                pty.write(self._copy_buffer)

    def _cmd_detach(self):
        self._running = False

    def _cmd_zoom_pane(self):
        pass   # zoom toggles are purely visual; left as extension point

    def _cmd_refresh_client(self):
        self._dirty = True

    def _cmd_show_time(self):
        pass   # show_time displayed in status bar already

    def _cmd_command_prompt(self):
        pass   # future extension: interactive command prompt

    def _cmd_choose_session(self):
        pass

    def _cmd_choose_window(self):
        pass

    def _cmd_rename_session(self):
        pass

    def _cmd_rename_window(self):
        pass

    def _cmd_list_keys(self):
        pass

    # ── SIGWINCH ──────────────────────────────────────────────────────────

    def _handle_sigwinch(self, signum, frame):
        rows, cols = get_terminal_size()
        for engine in self._layouts.values():
            engine.resize(rows, cols)
        for pane_id, pty_proc in self._ptys.items():
            geoms = {}
            for engine in self._layouts.values():
                geoms.update(engine.compute_geometries())
            g = geoms.get(pane_id)
            if g:
                pty_proc.resize(g.height, g.width)
        curses.resizeterm(rows, cols)
        self._dirty = True
