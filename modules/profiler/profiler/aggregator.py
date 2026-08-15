"""
Aggregates raw stack samples into a hierarchical call tree suitable for
rendering as a flame graph.

The tree is built by replaying every sample:

    For each sample (outermost → innermost):
        root → frame[0] → frame[1] → ... → frame[-1]

Each node accumulates:
    total_samples — how many samples pass through (or end at) this node
    self_samples  — how many samples end exactly at this node

self_samples / total_samples gives the fraction of time spent in that
function body (not in callees), i.e. the "self time" displayed in the
flame graph tooltip.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from config import FrameInfo, ProfileData, ProfilerConfig, Sample


@dataclass
class FlameNode:
    """One node in the flame graph call tree."""
    frame:          FrameInfo
    total_samples:  int = 0
    self_samples:   int = 0
    children:       dict[FrameInfo, "FlameNode"] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.frame)

    def all_nodes(self) -> list["FlameNode"]:
        """Depth-first traversal of this subtree."""
        result = [self]
        for child in self.children.values():
            result.extend(child.all_nodes())
        return result

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "filename":      self.frame.filename,
            "lineno":        self.frame.lineno,
            "funcname":      self.frame.funcname,
            "total_samples": self.total_samples,
            "self_samples":  self.self_samples,
            "children":      [c.to_dict() for c in self.children.values()],
        }


@dataclass
class FlameRoot:
    """Virtual root node that owns all top-level call trees."""
    total_samples: int = 0
    children:      dict[FrameInfo, FlameNode] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name":          "root",
            "total_samples": self.total_samples,
            "self_samples":  0,
            "children":      [c.to_dict() for c in self.children.values()],
        }

    def all_nodes(self) -> list[FlameNode]:
        result = []
        for child in self.children.values():
            result.extend(child.all_nodes())
        return result


class Aggregator:
    """
    Builds a FlameRoot call tree from a ProfileData.

    One FlameRoot is produced per thread if there are multiple threads,
    or a single root if merging all threads together.
    """

    def __init__(self, config: ProfilerConfig | None = None):
        self._cfg = config or ProfilerConfig()

    def aggregate(
        self,
        data: ProfileData,
        thread_id: int | None = None,
        merge_threads: bool = True,
    ) -> FlameRoot:
        """
        Aggregate samples into a call tree.

        Args:
            data:           ProfileData from a profiling session
            thread_id:      Only include samples from this thread (None = all)
            merge_threads:  If True, merge stacks from all threads into one tree
        """
        root = FlameRoot()

        for sample in data.samples:
            if thread_id is not None and sample.thread_id != thread_id:
                continue
            if not sample.stack:
                continue

            stack = sample.stack
            # Honour min_samples by deferring; we count everything first
            root.total_samples += 1
            self._insert_stack(root, stack)

        return root

    def per_thread_roots(self, data: ProfileData) -> dict[int, FlameRoot]:
        """Return one FlameRoot per thread."""
        result: dict[int, FlameRoot] = {}
        for tid in data.threads:
            result[tid] = self.aggregate(data, thread_id=tid)
        return result

    @staticmethod
    def hottest_functions(root: FlameRoot, n: int = 20) -> list[FlameNode]:
        """Return the N nodes with the highest self_samples."""
        nodes = root.all_nodes()
        return sorted(nodes, key=lambda x: x.self_samples, reverse=True)[:n]

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _insert_stack(root: FlameRoot, stack: tuple[FrameInfo, ...]):
        """Insert one stack trace into the tree, updating counts."""
        node_map = root.children

        for depth, frame in enumerate(stack):
            if frame not in node_map:
                node_map[frame] = FlameNode(frame=frame)
            node = node_map[frame]
            node.total_samples += 1

            if depth == len(stack) - 1:
                node.self_samples += 1

            node_map = node.children
