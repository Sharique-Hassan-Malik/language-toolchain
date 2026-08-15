"""
Session persistence.

Saves the current session layout (windows, pane geometry, working directories)
to a JSON file so it can be re-created after a restart.

Limitations:
  - Running processes cannot be saved; only the layout and shell CWDs are
    recorded.
  - On restore, a fresh shell is spawned in each pane at the saved CWD.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SessionPersistence:

    def __init__(self, path: str):
        self._path = Path(path)

    def save(self, sessions: list[dict]) -> bool:
        """
        Save session layout to disk.

        sessions: list of dicts, each representing a session with its
                  windows and pane geometries (as returned by _serialise).
        """
        try:
            self._path.write_text(json.dumps(sessions, indent=2))
            return True
        except OSError:
            return False

    def load(self) -> list[dict] | None:
        """Load saved sessions from disk; return None if file missing."""
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def delete(self):
        try:
            self._path.unlink()
        except OSError:
            pass


def serialise_session(session_name: str, windows: list[dict]) -> dict:
    return {"name": session_name, "windows": windows}


def serialise_window(window_name: str, panes: list[dict]) -> dict:
    return {"name": window_name, "panes": panes}


def serialise_pane(cwd: str, geometry: dict) -> dict:
    return {"cwd": cwd, "geometry": geometry}
