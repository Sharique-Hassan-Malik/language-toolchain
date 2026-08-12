# Architecture — Terminal Multiplexer

## Overview

A tmux-like terminal multiplexer implemented in pure Python using
pseudoterminals (`pty`), `curses` for rendering, and no external dependencies.

---

## Core Concepts

```
Session
  └── Window (one per "tab")
        └── Pane (one per split region)
              ├── PTY master fd  ←→  child shell process
              └── ScrollbackBuffer
```

A **Session** owns a list of Windows and a shared clipboard.

A **Window** manages a binary split tree of Panes and handles split/kill/zoom.

A **Pane** owns a PTY master file descriptor, a child shell process and a
`ScrollbackBuffer` that stores all terminal output.

---

## Pseudoterminal Model

Each pane creates a PTY pair with `pty.openpty()`:

```
┌────────────────────┐       ┌─────────────────────┐
│  multiplexer       │       │  child shell         │
│  (master fd)       │──────►│  (slave fd = stdin,  │
│                    │◄──────│   stdout, stderr)    │
└────────────────────┘       └─────────────────────┘
```

The multiplexer writes keystrokes to the master fd (the shell reads them as
stdin) and reads the shell's output from the master fd.

A background daemon thread per pane reads the master fd continuously and
appends data to the `ScrollbackBuffer`.

Window resizing sends `TIOCSWINSZ` ioctl to update the kernel's view of the
terminal dimensions so that programs inside the pane (vim, less, etc.) respond
correctly.

---

## ScrollbackBuffer

The buffer stores terminal output as a `deque` of rows, each row a `list[Cell]`.
Each `Cell` carries a character and an `Attr` tuple (fg, bg, bold, underline,
reverse, dim).

**Writing** processes one character at a time:
- Printable characters: stored at the cursor position.
- `\r`: reset column to 0.
- `\n`: advance row; if at the bottom of the visible height, append a new row
  to the deque.
- `\x08` (backspace): move column back one.
- ESC sequences: parsed as either CSI (`\x1b[...`) or OSC (`\x1b]...`).

**ANSI SGR** (Select Graphic Rendition) sequences update `_attr` which is
applied to subsequent characters.  All 8 standard foreground (30–37) and
background (40–47) colours are supported plus bright variants (90–97, 100–107)
and 256-colour mode (`\x1b[38;5;<n>m`).

**Scrolling** is implemented as a viewport offset (`_scroll_offset`) relative
to the bottom of the line deque.  Scrolling never modifies the stored lines.

**Copy mode** freezes the viewport and provides a vi-style cursor (`hjkl`)
that can be moved freely.  A selection region is defined by pressing Space
(mark start) and Enter (mark end / yank).  The yanked text is stored in the
session clipboard.

---

## Window Layout Tree

The window maintains a binary tree of `LayoutNode` objects:

```
LayoutNode = Pane | SplitNode

SplitNode:
    direction: HORIZONTAL | VERTICAL
    ratio: float (0–1, fraction for first child)
    first:  LayoutNode
    second: LayoutNode
```

**Splitting** replaces a leaf `Pane` node with a `SplitNode` containing the
original pane (resized to half) and a new pane.

**Killing** removes a leaf `Pane` node and replaces the parent `SplitNode` with
the surviving sibling.

**Re-layout** after resize or kill traverses the tree recursively and recomputes
each node's `Rect` based on the parent's rect and the `ratio`.

**Zooming** stores the active pane's rect, resizes it to fill the full window
rect, and sets a `_zoomed` flag.  Unzoom restores the saved rect.

---

## Renderer

The renderer is called once per frame (30 fps) from the multiplexer event loop.

For each pane:
1. Fetch the display lines from the buffer (`get_display_lines()`).
2. Iterate over each cell and call `stdscr.addch()` with the computed curses
   attribute (bold, underline, reverse, colour pair).
3. Draw border characters (`─`, `│`, `┼`) between adjacent panes.
4. Overlay the "process exited" message on dead panes.
5. Position the curses cursor at the active pane's cursor position.

The status bar at the bottom shows:
- Numbered window list with the active window highlighted.
- Session name and HH:MM clock on the right.

---

## Event Loop

The multiplexer runs a 30 fps loop:
1. Non-blocking `stdscr.get_wch()` to read the next key.
2. If the prefix (Ctrl-B) was received, set `_prefix_pending = True`.
3. On the next key after the prefix: look up the key in `BINDINGS` and
   dispatch the command.
4. Otherwise: forward the raw bytes to the active pane's PTY master fd.
5. Render the current session state.

---

## Session Persistence

`Session.save()` writes a JSON file with window names and pane geometry.
`Session.load_layout()` re-creates the window structure (new shells are started;
scrollback content is not restored).

---

## Files

```
termux/
├── termux.py                   — CLI entry point
├── config.py                   — Rect, Config, SplitDirection, BINDINGS
├── mux/
│   ├── buffer.py               — ScrollbackBuffer, Cell, Attr
│   ├── pane.py                 — Pane: PTY subprocess + buffer
│   ├── window.py               — Window: binary split tree
│   ├── session.py              — Session: window list + clipboard + persistence
│   ├── renderer.py             — Curses renderer
│   └── multiplexer.py          — Event loop and command dispatcher
├── tests/
│   └── test_termux.py          — 40+ offline tests
└── scripts/
```
