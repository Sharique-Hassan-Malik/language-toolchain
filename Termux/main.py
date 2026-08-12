#!/usr/bin/env python3
"""
termux — a tmux-like terminal multiplexer.

Usage:
    python main.py                     Start a new session
    python main.py -s mysession        Start (or attach to) named session
    python main.py --list              List saved sessions
    python main.py --kill mysession    Kill a named session

Default key bindings (prefix = Ctrl-B):
    "   split pane horizontally (top/bottom)
    %   split pane vertically (left/right)
    x   kill current pane
    z   zoom/unzoom current pane
    h/j/k/l or arrow keys  navigate panes
    c   new window
    n/p  next/previous window
    &   kill window
    [   enter copy/scroll mode (q to exit)
    ]   paste copy buffer
    d   detach
    ?   list keys
"""

import argparse
import os
import sys

from mux.config import MuxConfig
from mux.multiplexer import Multiplexer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="termux — terminal multiplexer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-s", "--session", default=None,
                   help="Session name (default: 'main')")
    p.add_argument("--shell",    default=None,
                   help="Shell to use (default: $SHELL)")
    p.add_argument("--list",     action="store_true",
                   help="List saved sessions and exit")
    p.add_argument("--kill",     default=None, metavar="SESSION",
                   help="Kill a saved session and exit")
    p.add_argument("--history",  type=int, default=2000,
                   help="Scrollback history lines (default: 2000)")
    p.add_argument("--no-mouse", action="store_true", dest="no_mouse")
    return p.parse_args()


def main():
    args = parse_args()

    if not sys.stdout.isatty():
        print("termux requires a terminal (TTY).", file=sys.stderr)
        sys.exit(1)

    config = MuxConfig(
        shell=args.shell or os.environ.get("SHELL", "/bin/bash"),
        history_limit=args.history,
        mouse=not args.no_mouse,
    )

    if args.list:
        from mux.persist import SessionPersistence
        sp = SessionPersistence(config.session_file)
        sessions = sp.load()
        if not sessions:
            print("No saved sessions.")
        else:
            for s in sessions:
                print(f"  {s['name']}  ({len(s.get('windows', []))} windows)")
        sys.exit(0)

    if args.kill:
        from mux.persist import SessionPersistence
        sp = SessionPersistence(config.session_file)
        sessions = sp.load() or []
        sessions = [s for s in sessions if s["name"] != args.kill]
        sp.save(sessions)
        print(f"Session '{args.kill}' removed.")
        sys.exit(0)

    mux = Multiplexer(config=config)
    mux.run()


if __name__ == "__main__":
    main()
