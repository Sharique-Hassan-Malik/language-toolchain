"""
WebAssembly type definitions.

Covers the complete MVP type system as defined in the spec:
  https://webassembly.github.io/spec/core/binary/types.html
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import NamedTuple


# ── Value types ────────────────────────────────────────────────────────────

class ValType(IntEnum):
    I32    = 0x7F
    I64    = 0x7E
    F32    = 0x7D
    F64    = 0x7C
    # Reference types (post-MVP but widely supported)
    FUNCREF   = 0x70
    EXTERNREF = 0x6F

    def __str__(self):
        return self.name.lower()


# ── Function type ──────────────────────────────────────────────────────────

class FuncType(NamedTuple):
    params:  tuple[ValType, ...]
    results: tuple[ValType, ...]

    def __str__(self):
        p = ", ".join(str(t) for t in self.params)
        r = ", ".join(str(t) for t in self.results)
        return f"({p}) -> ({r})"


# ── Limits ─────────────────────────────────────────────────────────────────

class Limits(NamedTuple):
    min: int
    max: int | None   # None = unbounded


# ── Memory, table, global types ────────────────────────────────────────────

class MemType(NamedTuple):
    limits: Limits


class TableType(NamedTuple):
    elem_type: ValType
    limits:    Limits


@dataclass
class GlobalType:
    val_type: ValType
    mutable:  bool


# ── Block type ─────────────────────────────────────────────────────────────

class BlockType:
    """Represents the type annotation on block/loop/if instructions."""

    EMPTY = None    # void block

    def __init__(self, val_type: ValType | None = None, type_idx: int | None = None):
        self.val_type = val_type   # single result type (shorthand encoding)
        self.type_idx = type_idx   # index into types section (multi-value)

    def result_count(self) -> int:
        if self.val_type is None and self.type_idx is None:
            return 0
        if self.val_type is not None:
            return 1
        # type_idx case: caller must look up the function type
        return -1  # sentinel — caller handles


# ── Reader helpers (used by module parser) ─────────────────────────────────

def read_val_type(r) -> ValType:
    b = r.read_byte()
    try:
        return ValType(b)
    except ValueError:
        raise ValueError(f"Unknown valtype 0x{b:02x} at {r.pos}")


def read_func_type(r) -> FuncType:
    tag = r.read_byte()
    if tag != 0x60:
        raise ValueError(f"Expected functype tag 0x60, got 0x{tag:02x}")
    params  = tuple(read_val_type(r) for _ in range(r.read_u32()))
    results = tuple(read_val_type(r) for _ in range(r.read_u32()))
    return FuncType(params, results)


def read_limits(r) -> Limits:
    flag = r.read_byte()
    lo   = r.read_u32()
    hi   = r.read_u32() if flag else None
    return Limits(lo, hi)


def read_mem_type(r) -> MemType:
    return MemType(read_limits(r))


def read_table_type(r) -> TableType:
    et  = read_val_type(r)
    lim = read_limits(r)
    return TableType(et, lim)


def read_global_type(r) -> GlobalType:
    vt  = read_val_type(r)
    mut = bool(r.read_byte())
    return GlobalType(vt, mut)


def read_block_type(r) -> BlockType:
    b = r.peek()
    if b == 0x40:
        r.read_byte()
        return BlockType()
    # Try as valtype
    try:
        vt = ValType(b)
        r.read_byte()
        return BlockType(val_type=vt)
    except ValueError:
        pass
    # Signed LEB128 type index
    idx = r.read_i32()
    if idx < 0:
        raise ValueError(f"Negative block type index {idx}")
    return BlockType(type_idx=idx)
