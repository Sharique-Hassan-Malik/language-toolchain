from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_PANES      = 16
MAX_SESSIONS   = 8
SCROLLBACK     = 2000       # lines kept in scrollback buffer per pane
COPY_BUFFER    = 65536      # bytes in the copy buffer
STATUS_HEIGHT  = 1          # rows taken by the status bar


# ---------------------------------------------------------------------------
# Key bindings  (prefix key = Ctrl-B, matching tmux defaults)
# ---------------------------------------------------------------------------

PREFIX_KEY = "\x02"    # Ctrl-B

BINDINGS: dict[str, str] = {
    # Pane management
    '"':  "split_horizontal",
    "%":  "split_vertical",
    "x":  "kill_pane",
    "z":  "zoom_pane",
    # Navigation
    "h":  "focus_left",
    "j":  "focus_down",
    "k":  "focus_up",
    "l":  "focus_right",
    "\x1b[D": "focus_left",     # Arrow left
    "\x1b[B": "focus_down",     # Arrow down
    "\x1b[A": "focus_up",       # Arrow up
    "\x1b[C": "focus_right",    # Arrow right
    # Sessions
    "s":  "choose_session",
    "d":  "detach",
    "$":  "rename_session",
    # Windows
    "c":  "new_window",
    "n":  "next_window",
    "p":  "prev_window",
    "&":  "kill_window",
    ",":  "rename_window",
    "w":  "choose_window",
    # Scrollback / copy mode
    "[":  "enter_copy_mode",
    "]":  "paste_buffer",
    # Misc
    "?":  "list_keys",
    ":":  "command_prompt",
    "t":  "show_time",
    "r":  "refresh_client",
}


# ---------------------------------------------------------------------------
# Resize direction
# ---------------------------------------------------------------------------

class Direction(Enum):
    LEFT  = auto()
    RIGHT = auto()
    UP    = auto()
    DOWN  = auto()


# ---------------------------------------------------------------------------
# Pane / window / session state (data only — no curses)
# ---------------------------------------------------------------------------

@dataclass
class PaneGeometry:
    x:      int    # column offset within the terminal
    y:      int    # row offset
    width:  int
    height: int


@dataclass
class PaneState:
    pane_id:    int
    geometry:   PaneGeometry
    pid:        int  = 0       # child process PID
    fd:         int  = -1      # master pty fd
    title:      str  = ""
    scrollback: list = field(default_factory=list)   # list[str]
    scroll_pos: int  = 0       # 0 = bottom of buffer
    zoomed:     bool = False
    alive:      bool = True


@dataclass
class WindowState:
    window_id:    int
    name:         str
    panes:        list[PaneState]  = field(default_factory=list)
    active_pane:  int              = 0       # index into panes

    @property
    def active(self) -> PaneState | None:
        if not self.panes:
            return None
        return self.panes[self.active_pane % len(self.panes)]


@dataclass
class SessionState:
    session_id:    int
    name:          str
    windows:       list[WindowState]  = field(default_factory=list)
    active_window: int                = 0

    @property
    def active(self) -> WindowState | None:
        if not self.windows:
            return None
        return self.windows[self.active_window % len(self.windows)]


@dataclass
class MuxConfig:
    shell:          str   = os.environ.get("SHELL", "/bin/bash")
    session_file:   str   = os.path.expanduser("~/.termux_sessions")
    default_term:   str   = "xterm-256color"
    history_limit:  int   = SCROLLBACK
    mouse:          bool  = False
    status_interval: int  = 5    # seconds between status bar refresh
