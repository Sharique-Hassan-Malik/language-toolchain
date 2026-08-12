"""
Test suite for the terminal multiplexer.

All tests run fully offline — no curses, no PTYs, no child processes.

Run with:
    python -m pytest tests/test_mux.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mux.config import PaneGeometry, PaneState, WindowState, SessionState, BINDINGS
from mux.layout import LayoutEngine, LayoutNode, SplitDir
from mux.scrollback import ScrollbackBuffer
from mux.persist import SessionPersistence, serialise_session, serialise_window, serialise_pane


# ---------------------------------------------------------------------------
# LayoutNode
# ---------------------------------------------------------------------------

class TestLayoutNode:

    def test_leaf_is_leaf(self):
        n = LayoutNode(pane_id=0)
        assert n.is_leaf

    def test_internal_not_leaf(self):
        n = LayoutNode(children=[LayoutNode(pane_id=0), LayoutNode(pane_id=1)])
        n.split = SplitDir.HORIZONTAL
        assert not n.is_leaf

    def test_leaves_single(self):
        n = LayoutNode(pane_id=5)
        assert list(n.leaves()) == [n]

    def test_leaves_two(self):
        left  = LayoutNode(pane_id=0)
        right = LayoutNode(pane_id=1)
        root  = LayoutNode(split=SplitDir.HORIZONTAL, children=[left, right])
        ids   = [l.pane_id for l in root.leaves()]
        assert set(ids) == {0, 1}

    def test_find_existing(self):
        left  = LayoutNode(pane_id=3)
        right = LayoutNode(pane_id=7)
        root  = LayoutNode(split=SplitDir.HORIZONTAL, children=[left, right])
        assert root.find(3) is left
        assert root.find(7) is right

    def test_find_missing(self):
        n = LayoutNode(pane_id=0)
        assert n.find(99) is None

    def test_remove_collapses(self):
        left  = LayoutNode(pane_id=0)
        right = LayoutNode(pane_id=1)
        root  = LayoutNode(split=SplitDir.HORIZONTAL, children=[left, right])
        root.remove(1)
        assert root.is_leaf
        assert root.pane_id == 0

    def test_remove_preserves_sibling(self):
        left  = LayoutNode(pane_id=0)
        right = LayoutNode(pane_id=1)
        root  = LayoutNode(split=SplitDir.HORIZONTAL, children=[left, right])
        root.remove(0)
        assert root.pane_id == 1


# ---------------------------------------------------------------------------
# LayoutEngine
# ---------------------------------------------------------------------------

class TestLayoutEngine:

    def test_add_initial(self):
        e = LayoutEngine(24, 80)
        pid = e.add_initial()
        assert pid == 0
        geoms = e.compute_geometries()
        assert pid in geoms

    def test_initial_geometry_fills_screen(self):
        e = LayoutEngine(24, 80)
        pid = e.add_initial()
        g   = e.compute_geometries()[pid]
        assert g.width  == 80
        assert g.height == 24 - 1   # minus status bar

    def test_split_vertical_creates_two_panes(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.VERTICAL)
        assert p1 is not None
        geoms = e.compute_geometries()
        assert p0 in geoms and p1 in geoms

    def test_split_horizontal_creates_two_panes(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.HORIZONTAL)
        assert p1 is not None
        geoms = e.compute_geometries()
        assert p0 in geoms and p1 in geoms

    def test_vertical_split_equal_widths(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.VERTICAL)
        geoms = e.compute_geometries()
        # After a vertical split the rows should be roughly equal
        h0 = geoms[p0].height
        h1 = geoms[p1].height
        assert abs(h0 - h1) <= 2

    def test_horizontal_split_equal_heights(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.HORIZONTAL)
        geoms = e.compute_geometries()
        w0 = geoms[p0].width
        w1 = geoms[p1].width
        assert abs(w0 - w1) <= 2

    def test_pane_ids_reflects_all(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.VERTICAL)
        assert set(e.pane_ids()) == {p0, p1}

    def test_remove_single_pane(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        e.remove(p0)
        assert e.pane_ids() == []

    def test_remove_second_pane(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.VERTICAL)
        e.remove(p1)
        assert e.pane_ids() == [p0]

    def test_resize_updates_dimensions(self):
        e = LayoutEngine(24, 80)
        e.add_initial()
        e.resize(48, 160)
        assert e.rows == 48
        assert e.cols == 160

    def test_no_split_when_too_small(self):
        e  = LayoutEngine(24, 3)    # only 3 columns
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.HORIZONTAL)
        assert p1 is None

    def test_neighbour_horizontal(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        p1 = e.split(p0, SplitDir.HORIZONTAL)
        # p1 should be to the right of p0
        n = e.neighbour(p0, SplitDir.HORIZONTAL, prefer_second=True)
        assert n == p1

    def test_no_neighbour_when_only_one_pane(self):
        e  = LayoutEngine(24, 80)
        p0 = e.add_initial()
        assert e.neighbour(p0, SplitDir.HORIZONTAL, prefer_second=True) is None


# ---------------------------------------------------------------------------
# ScrollbackBuffer
# ---------------------------------------------------------------------------

class TestScrollback:

    def test_append_and_visible(self):
        sb = ScrollbackBuffer(capacity=100)
        sb.append(b"line1")
        sb.append(b"line2")
        lines = sb.visible_lines(10)
        assert b"line1" in lines
        assert b"line2" in lines

    def test_visible_pads_short_buffer(self):
        sb = ScrollbackBuffer(capacity=100)
        sb.append(b"only")
        lines = sb.visible_lines(5)
        assert len(lines) == 5

    def test_scroll_up_shifts_view(self):
        sb = ScrollbackBuffer(capacity=100)
        for i in range(20):
            sb.append(f"line{i}".encode())
        sb.scroll_up(5)
        assert sb.scroll_pos == 5

    def test_scroll_down_clamps_at_zero(self):
        sb = ScrollbackBuffer(capacity=100)
        sb.append(b"x")
        sb.scroll_down(99)
        assert sb.scroll_pos == 0

    def test_at_bottom_initially(self):
        sb = ScrollbackBuffer()
        assert sb.at_bottom

    def test_not_at_bottom_after_scroll_up(self):
        sb = ScrollbackBuffer(capacity=100)
        for _ in range(10):
            sb.append(b"x")
        sb.scroll_up(3)
        assert not sb.at_bottom

    def test_scroll_to_bottom(self):
        sb = ScrollbackBuffer(capacity=100)
        for _ in range(10):
            sb.append(b"x")
        sb.scroll_up(5)
        sb.scroll_to_bottom()
        assert sb.at_bottom

    def test_capacity_limit(self):
        sb = ScrollbackBuffer(capacity=5)
        for i in range(10):
            sb.append(f"line{i}".encode())
        assert len(sb) == 5

    def test_copy_mode_enter_exit(self):
        sb = ScrollbackBuffer()
        sb.enter_copy_mode()
        assert sb.in_copy_mode
        sb.exit_copy_mode()
        assert not sb.in_copy_mode

    def test_copy_mode_cursor_move(self):
        sb = ScrollbackBuffer()
        sb.enter_copy_mode()
        sb.cursor_move(2, 5, 24, 80)
        assert sb.cursor == (2, 5)

    def test_copy_selection(self):
        sb = ScrollbackBuffer(capacity=100)
        sb.append(b"hello world")
        sb.enter_copy_mode()
        sb.cursor_move(0, 0, 5, 80)
        lines = sb.visible_lines(5)
        result = sb.copy_selection(lines)
        assert isinstance(result, bytes)

    def test_append_chunk_splits_newlines(self):
        sb = ScrollbackBuffer(capacity=100)
        sb.append_chunk(b"line1\nline2\nline3")
        assert len(sb) >= 3

    def test_copy_buffer_accessible(self):
        sb = ScrollbackBuffer()
        assert sb.copy_buffer == b""


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_save_and_load(self, tmp_path):
        sp = SessionPersistence(str(tmp_path / "sessions.json"))
        sessions = [
            serialise_session("main", [
                serialise_window("bash", [
                    serialise_pane("/home/user", {"x": 0, "y": 0, "width": 80, "height": 23})
                ])
            ])
        ]
        assert sp.save(sessions)
        loaded = sp.load()
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "main"

    def test_load_missing_returns_none(self, tmp_path):
        sp = SessionPersistence(str(tmp_path / "nonexistent.json"))
        assert sp.load() is None

    def test_delete(self, tmp_path):
        path = tmp_path / "s.json"
        sp   = SessionPersistence(str(path))
        sp.save([{"name": "x"}])
        sp.delete()
        assert not path.exists()

    def test_corrupted_file_returns_none(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{{")
        sp = SessionPersistence(str(path))
        assert sp.load() is None

    def test_session_structure(self):
        s = serialise_session("test", [])
        assert s["name"] == "test"
        assert "windows" in s

    def test_window_structure(self):
        w = serialise_window("bash", [])
        assert w["name"] == "bash"
        assert "panes" in w

    def test_pane_structure(self):
        p = serialise_pane("/tmp", {"x": 0})
        assert p["cwd"] == "/tmp"
        assert "geometry" in p


# ---------------------------------------------------------------------------
# Config and bindings
# ---------------------------------------------------------------------------

class TestConfig:

    def test_bindings_not_empty(self):
        assert len(BINDINGS) > 5

    def test_prefix_commands_all_defined(self):
        # All binding values should be plausible command names (strings)
        for key, cmd in BINDINGS.items():
            assert isinstance(cmd, str)
            assert len(cmd) > 0

    def test_split_commands_present(self):
        assert "split_horizontal" in BINDINGS.values()
        assert "split_vertical"   in BINDINGS.values()

    def test_navigation_commands_present(self):
        assert "focus_left"  in BINDINGS.values()
        assert "focus_right" in BINDINGS.values()
        assert "focus_up"    in BINDINGS.values()
        assert "focus_down"  in BINDINGS.values()
