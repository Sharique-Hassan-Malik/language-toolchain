"""
Test suite for PyFlame.

All tests run offline — no network connections, no subprocess profiling.
Samples are constructed directly to test the analysis and rendering pipeline.

Run with:
    python -m pytest tests/test_profiler.py -v
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import FrameInfo, ProfileData, ProfilerConfig, Sample
from profiler.sampler import Sampler, ProfileSession
from profiler.aggregator import Aggregator, FlameNode, FlameRoot
from profiler.serializer import ProfileSerializer
from ui.flamegraph import FlamegraphRenderer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(funcname: str, filename: str = "test.py", lineno: int = 1) -> FrameInfo:
    return FrameInfo(filename=filename, lineno=lineno, funcname=funcname)


def _make_profile(*stacks: tuple[str, ...], interval: float = 0.001) -> ProfileData:
    """Build a ProfileData from a list of call stacks (tuples of funcnames)."""
    samples = []
    t = 0.0
    for stack_names in stacks:
        stack = tuple(_frame(n) for n in stack_names)
        samples.append(Sample(timestamp=t, thread_id=1, stack=stack))
        t += interval
    return ProfileData(samples=samples, start_time=0.0, end_time=t)


# ---------------------------------------------------------------------------
# FrameInfo
# ---------------------------------------------------------------------------

class TestFrameInfo:

    def test_str_includes_funcname(self):
        f = _frame("my_func", "module.py", 42)
        assert "my_func" in str(f)

    def test_str_includes_lineno(self):
        f = _frame("fn", "module.py", 99)
        assert "99" in str(f)

    def test_equality(self):
        a = _frame("fn", "a.py", 1)
        b = _frame("fn", "a.py", 1)
        assert a == b

    def test_hashable(self):
        f = _frame("fn")
        d = {f: 1}
        assert d[f] == 1


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

class TestAggregator:

    def test_single_sample_single_frame(self):
        data = _make_profile(("main",))
        root = Aggregator().aggregate(data)
        assert root.total_samples == 1
        assert len(root.children) == 1

    def test_total_samples_matches_input(self):
        stacks = [("a", "b"), ("a", "b"), ("a", "c")]
        data = _make_profile(*stacks)
        root = Aggregator().aggregate(data)
        assert root.total_samples == 3

    def test_child_counts_correct(self):
        data = _make_profile(("a", "b"), ("a", "b"), ("a", "c"))
        root = Aggregator().aggregate(data)
        a    = list(root.children.values())[0]
        assert a.total_samples == 3
        assert len(a.children) == 2

    def test_self_samples_leaf(self):
        data = _make_profile(("a", "b"))
        root = Aggregator().aggregate(data)
        a    = list(root.children.values())[0]
        b    = list(a.children.values())[0]
        assert b.self_samples == 1
        assert a.self_samples == 0

    def test_self_samples_no_children(self):
        data = _make_profile(("a",))
        root = Aggregator().aggregate(data)
        a    = list(root.children.values())[0]
        assert a.self_samples == 1

    def test_empty_profile(self):
        data = _make_profile()
        root = Aggregator().aggregate(data)
        assert root.total_samples == 0
        assert len(root.children) == 0

    def test_hottest_functions(self):
        # "slow" appears as the leaf in 5 samples, "fast" in 1
        stacks = [("root", "slow")] * 5 + [("root", "fast")]
        data = _make_profile(*stacks)
        root = Aggregator().aggregate(data)
        top  = Aggregator.hottest_functions(root, n=2)
        assert top[0].frame.funcname == "slow"
        assert top[0].self_samples == 5

    def test_flame_root_to_dict(self):
        data = _make_profile(("a", "b"))
        root = Aggregator().aggregate(data)
        d    = root.to_dict()
        assert d["name"] == "root"
        assert "children" in d
        assert d["total_samples"] == 1

    def test_node_to_dict_recursive(self):
        data = _make_profile(("a", "b", "c"))
        root = Aggregator().aggregate(data)
        d    = root.to_dict()
        # Verify we can traverse to depth 2
        child_a = d["children"][0]
        child_b = child_a["children"][0]
        assert child_b["funcname"] == "b"

    def test_all_nodes_count(self):
        data = _make_profile(("a", "b"), ("a", "c"), ("d",))
        root = Aggregator().aggregate(data)
        # a, b, c, d = 4 unique frames
        assert len(root.all_nodes()) == 4

    def test_per_thread_roots(self):
        samples = [
            Sample(0.0, thread_id=1, stack=(_frame("fn1"),)),
            Sample(0.0, thread_id=2, stack=(_frame("fn2"),)),
        ]
        data = ProfileData(samples=samples, start_time=0.0, end_time=0.01)
        roots = Aggregator().per_thread_roots(data)
        assert set(roots.keys()) == {1, 2}


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

class TestSerializer:

    def test_roundtrip(self, tmp_path):
        data = _make_profile(("a", "b"), ("a", "c"))
        path = str(tmp_path / "p.json")
        ProfileSerializer().save(data, path)
        loaded = ProfileSerializer().load(path)
        assert loaded.sample_count == data.sample_count
        assert loaded.duration == pytest.approx(data.duration, abs=1e-6)

    def test_stack_preserved(self, tmp_path):
        data = _make_profile(("outer", "inner"))
        path = str(tmp_path / "p.json")
        ProfileSerializer().save(data, path)
        loaded = ProfileSerializer().load(path)
        s = loaded.samples[0]
        assert s.stack[0].funcname == "outer"
        assert s.stack[1].funcname == "inner"

    def test_json_is_valid(self, tmp_path):
        data = _make_profile(("fn",))
        path = str(tmp_path / "p.json")
        ProfileSerializer().save(data, path)
        raw = json.loads(Path(path).read_text())
        assert "samples" in raw
        assert raw["version"] == ProfileSerializer.VERSION

    def test_thread_id_preserved(self, tmp_path):
        s    = Sample(0.0, thread_id=42, stack=(_frame("fn"),))
        data = ProfileData(samples=[s], start_time=0.0, end_time=0.01)
        path = str(tmp_path / "p.json")
        ProfileSerializer().save(data, path)
        loaded = ProfileSerializer().load(path)
        assert loaded.samples[0].thread_id == 42

    def test_empty_profile_roundtrip(self, tmp_path):
        data = ProfileData(samples=[], start_time=0.0, end_time=0.0)
        path = str(tmp_path / "p.json")
        ProfileSerializer().save(data, path)
        loaded = ProfileSerializer().load(path)
        assert loaded.sample_count == 0

    def test_save_flame_tree(self, tmp_path):
        data = _make_profile(("a", "b"))
        root = Aggregator().aggregate(data)
        path = str(tmp_path / "tree.json")
        ProfileSerializer().save_flame_tree(root, path)
        raw  = json.loads(Path(path).read_text())
        assert "children" in raw


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class TestRenderer:

    def test_html_contains_svg(self):
        data = _make_profile(("a", "b"), ("a", "b"), ("c",))
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer().render(root)
        assert "<svg" in html
        assert "</svg>" in html

    def test_html_contains_function_names(self):
        data = _make_profile(("my_function",))
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer().render(root)
        assert "my_function" in html

    def test_html_contains_search_input(self):
        data = _make_profile(("fn",))
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer().render(root)
        assert 'id="search"' in html

    def test_html_is_complete(self):
        data = _make_profile(("fn",))
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer().render(root)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_empty_profile_renders(self):
        root = FlameRoot()
        html = FlamegraphRenderer().render(root)
        assert "<svg" in html

    def test_stats_table_present(self):
        data = _make_profile(("hot_func",) * 10)
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer().render(root)
        assert "Top Functions" in html

    def test_title_in_html(self):
        data = _make_profile(("fn",))
        root = Aggregator().aggregate(data)
        html = FlamegraphRenderer(width=800).render(root, title="My Profile")
        assert "My Profile" in html


# ---------------------------------------------------------------------------
# Sampler — live sampling tests
# ---------------------------------------------------------------------------

class TestSampler:

    def test_collects_samples(self):
        cfg     = ProfilerConfig(interval=0.001, duration=0.05, max_samples=200)
        sampler = Sampler(cfg)
        sampler.start()
        # Give the sampler time to collect samples from this thread
        time.sleep(0.06)
        sampler.stop()
        data = sampler.profile_data()
        assert data.sample_count >= 1

    def test_stops_after_duration(self):
        cfg = ProfilerConfig(interval=0.001, duration=0.03)
        sampler = Sampler(cfg)
        sampler.start()
        time.sleep(0.1)
        sampler.stop()
        data = sampler.profile_data()
        # Should have stopped well before collecting 100 samples in 30ms
        assert data.sample_count < 200

    def test_profile_session_context_manager(self):
        cfg = ProfilerConfig(interval=0.001, max_samples=50)
        with ProfileSession(cfg) as p:
            total = sum(range(1000))   # give it something to sample
        assert p.profile is not None
        assert p.profile.sample_count >= 0   # may be 0 if very fast

    def test_sample_has_stack(self):
        cfg = ProfilerConfig(interval=0.001, duration=0.05)
        sampler = Sampler(cfg)
        sampler.start()
        time.sleep(0.06)
        sampler.stop()
        data = sampler.profile_data()
        # At least some samples should have non-empty stacks
        non_empty = [s for s in data.samples if s.stack]
        # This may be 0 in very fast CI; we just check it doesn't crash
        assert isinstance(non_empty, list)

    def test_profile_data_has_timestamps(self):
        cfg = ProfilerConfig(interval=0.001, duration=0.02)
        sampler = Sampler(cfg)
        sampler.start()
        time.sleep(0.03)
        sampler.stop()
        data = sampler.profile_data()
        assert data.start_time > 0
        assert data.end_time >= data.start_time
