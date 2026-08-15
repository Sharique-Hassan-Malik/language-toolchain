"""
Layout engine.

Panes are arranged using a binary-tree split model:
  - Horizontal split (%): left pane | right pane
  - Vertical split ("): top pane / bottom pane

Each leaf node in the tree holds a pane_id.  Intermediate nodes hold the
split direction and ratio.

The layout engine computes PaneGeometry (x, y, width, height) for every
leaf by recursively partitioning a root rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator

from mux.config import PaneGeometry, STATUS_HEIGHT


class SplitDir(Enum):
    HORIZONTAL = auto()   # left | right
    VERTICAL   = auto()   # top  / bottom


@dataclass
class LayoutNode:
    """Binary tree node for the split layout."""
    pane_id:    int | None  = None   # non-None for leaf nodes
    split:      SplitDir | None = None
    ratio:      float       = 0.5    # fraction given to the first child
    children:   list["LayoutNode"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return self.pane_id is not None

    def leaves(self) -> Iterator["LayoutNode"]:
        if self.is_leaf:
            yield self
        else:
            for child in self.children:
                yield from child.leaves()

    def find(self, pane_id: int) -> "LayoutNode | None":
        if self.pane_id == pane_id:
            return self
        for child in self.children:
            result = child.find(pane_id)
            if result:
                return result
        return None

    def remove(self, pane_id: int) -> bool:
        """Remove a leaf node; collapse parent if only one child remains."""
        for i, child in enumerate(self.children):
            if child.is_leaf and child.pane_id == pane_id:
                self.children.pop(i)
                if len(self.children) == 1:
                    # Collapse: replace self with sole remaining child
                    sole = self.children[0]
                    self.pane_id  = sole.pane_id
                    self.split    = sole.split
                    self.ratio    = sole.ratio
                    self.children = sole.children
                return True
            if child.remove(pane_id):
                return True
        return False


class LayoutEngine:
    """
    Manages the split tree for one window and computes geometry for all panes.
    """

    def __init__(self, rows: int, cols: int):
        self.rows  = rows
        self.cols  = cols
        self._tree: LayoutNode | None = None
        self._next_id = 0

    # ── Public API ────────────────────────────────────────────────────────

    def add_initial(self) -> int:
        pane_id    = self._next_id
        self._next_id += 1
        self._tree = LayoutNode(pane_id=pane_id)
        return pane_id

    def split(self, active_pane: int, direction: SplitDir) -> int | None:
        """
        Split the active pane in the given direction.
        Returns the new pane_id or None if the pane is too small to split.
        """
        if self._tree is None:
            return None

        node = self._find_node(active_pane)
        if node is None:
            return None

        # Check minimum size before splitting
        geom = self._geometry_for(active_pane)
        if geom:
            if direction == SplitDir.HORIZONTAL and geom.width < 4:
                return None
            if direction == SplitDir.VERTICAL and geom.height < 4:
                return None

        new_id = self._next_id
        self._next_id += 1

        # Convert the leaf into an internal node
        old_leaf = LayoutNode(pane_id=active_pane)
        new_leaf = LayoutNode(pane_id=new_id)
        node.pane_id  = None
        node.split    = direction
        node.ratio    = 0.5
        node.children = [old_leaf, new_leaf]

        return new_id

    def remove(self, pane_id: int):
        if self._tree:
            if self._tree.is_leaf and self._tree.pane_id == pane_id:
                self._tree = None
            else:
                self._tree.remove(pane_id)

    def compute_geometries(self) -> dict[int, PaneGeometry]:
        """Return {pane_id: PaneGeometry} for all panes in the current layout."""
        result: dict[int, PaneGeometry] = {}
        if self._tree is None:
            return result
        usable_rows = self.rows - STATUS_HEIGHT
        self._compute(self._tree, 0, 0, self.cols, usable_rows, result)
        return result

    def pane_ids(self) -> list[int]:
        if not self._tree:
            return []
        return [n.pane_id for n in self._tree.leaves()]

    def resize(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols

    # ── Navigation helpers ────────────────────────────────────────────────

    def neighbour(self, active: int, direction: SplitDir, prefer_second: bool) -> int | None:
        """
        Find the pane adjacent to `active` in the given split direction.
        Used to implement focus movement.
        """
        geometries = self.compute_geometries()
        if active not in geometries:
            return None
        ag = geometries[active]

        candidates = []
        for pid, g in geometries.items():
            if pid == active:
                continue
            if direction == SplitDir.HORIZONTAL:
                if prefer_second:
                    if g.x >= ag.x + ag.width and _overlap_v(ag, g):
                        candidates.append((g.x, pid))
                else:
                    if g.x + g.width <= ag.x and _overlap_v(ag, g):
                        candidates.append((-g.x, pid))
            else:
                if prefer_second:
                    if g.y >= ag.y + ag.height and _overlap_h(ag, g):
                        candidates.append((g.y, pid))
                else:
                    if g.y + g.height <= ag.y and _overlap_h(ag, g):
                        candidates.append((-g.y, pid))

        if not candidates:
            return None
        return min(candidates)[1]

    # ── Internal ──────────────────────────────────────────────────────────

    def _compute(
        self,
        node: LayoutNode,
        x: int, y: int, w: int, h: int,
        result: dict[int, PaneGeometry],
    ):
        if node.is_leaf:
            result[node.pane_id] = PaneGeometry(x=x, y=y, width=w, height=h)
            return

        if node.split == SplitDir.HORIZONTAL:
            w1 = max(1, int(w * node.ratio))
            w2 = max(1, w - w1 - 1)   # -1 for divider
            self._compute(node.children[0], x,       y, w1, h, result)
            self._compute(node.children[1], x + w1 + 1, y, w2, h, result)
        else:
            h1 = max(1, int(h * node.ratio))
            h2 = max(1, h - h1 - 1)
            self._compute(node.children[0], x, y,       w, h1, result)
            self._compute(node.children[1], x, y + h1 + 1, w, h2, result)

    def _find_node(self, pane_id: int) -> LayoutNode | None:
        return self._tree.find(pane_id) if self._tree else None

    def _geometry_for(self, pane_id: int) -> PaneGeometry | None:
        return self.compute_geometries().get(pane_id)


def _overlap_v(a: PaneGeometry, b: PaneGeometry) -> bool:
    return a.y < b.y + b.height and b.y < a.y + a.height


def _overlap_h(a: PaneGeometry, b: PaneGeometry) -> bool:
    return a.x < b.x + b.width and b.x < a.x + a.width
