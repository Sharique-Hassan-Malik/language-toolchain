# Terminal Multiplexer

> Part of the [Language Toolchain](../../README.md). Runs standalone from this
> folder; `lang` joins the compiler, runtime and profiler into one pipeline.

A tmux-like terminal multiplexer in pure Python — split panes, multiple
windows, scrollback buffer, copy mode and session persistence.

Built on pseudoterminals (`pty`), `curses` and the standard library.
No external dependencies.

---

## Features

- Multiple windows (like tmux's "windows")
- Horizontal and vertical pane splitting
- Scrollback buffer (configurable depth, default 1000 lines)
- ANSI colour and attribute support in the scrollback (SGR sequences)
- Copy mode: vi-style cursor navigation, text selection and session clipboard
- Zoom/unzoom the active pane to full screen
- Per-pane PTY with `TIOCSWINSZ` resize propagation
- Status bar: window list, session name, clock
- Session persistence (layout save/restore to JSON)
- 40+ offline pytest tests — no PTY or curses needed

---

## Requirements

Python 3.11+ — no runtime dependencies.

```bash
pip install pytest   # for running tests only
```

---

## Usage

```bash
python termux.py                        # start with default settings
python termux.py -s my-session          # named session
python termux.py --shell /bin/zsh       # custom shell
python termux.py --scrollback 5000      # larger scrollback
python termux.py --save-on-exit layout.json  # persist layout on exit
```

---

## Key Bindings

All bindings are triggered by **Ctrl-B** followed by the listed key.

| Key | Action |
|-----|--------|
| `c` | New window |
| `n` / `p` | Next / previous window |
| `"` | Split horizontally (top/bottom) |
| `%` | Split vertically (left/right) |
| `o` | Cycle to next pane |
| Arrow keys | Select pane in that direction |
| `x` | Kill active pane |
| `&` | Kill active window |
| `z` | Zoom / unzoom active pane |
| `[` | Enter copy mode |
| `]` | Paste clipboard |
| `d` | Detach (exit) |
| `,` | Rename window |
| `$` | Rename session |
| `?` | Help overlay |

### Copy mode keys (after `[`)

| Key | Action |
|-----|--------|
| `h j k l` | Move cursor left / down / up / right |
| `u` / `d` | Scroll up / down 5 lines |
| Space | Mark selection start |
| Enter | Mark selection end and yank |
| `q` / Esc | Exit copy mode |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Architecture Summary

```
Session
  clipboard
  └── Window (window list, active window)
        split tree (binary)
        └── Pane
              PTY master fd ←→ child shell
              background reader thread
              ScrollbackBuffer
                  deque[list[Cell]]
                  Cell(char, Attr)

Renderer (curses, 30 fps)
  draw each pane's buffer cells
  draw borders between panes
  draw status bar

Multiplexer (event loop)
  Ctrl-B prefix dispatch → commands
  everything else → active pane PTY
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of the PTY
model, scrollback buffer design, split tree layout algorithm and copy mode.

---

## Project Structure

```
termux/
├── termux.py
├── config.py
├── mux/
│   ├── buffer.py
│   ├── pane.py
│   ├── window.py
│   ├── session.py
│   ├── renderer.py
│   └── multiplexer.py
├── tests/
│   └── test_termux.py
└── scripts/
```
