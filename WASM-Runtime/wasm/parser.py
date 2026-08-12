"""
WebAssembly binary module parser.

Parses all standard sections of a .wasm binary into Python dataclasses:
  1  Type       function signatures
  2  Import     external function/memory/table/global imports
  3  Function   function type index table
  4  Table      table definitions
  5  Memory     memory definitions
  6  Global     global variable definitions
  7  Export     exported names
  8  Start      optional start function index
  9  Element    table initialisation segments
  10 Code       function bodies (locals + instructions)
  11 Data       memory initialisation segments
  12 DataCount  (bulk memory extension)

Custom sections are stored verbatim.

Reference: https://webassembly.github.io/spec/core/binary/modules.html
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from wasm.binary import BinaryReader
from wasm.types import (
    FuncType, GlobalType, Limits, MemType, TableType, ValType,
    read_func_type, read_global_type, read_limits, read_mem_type,
    read_table_type, read_val_type,
)
from wasm.instructions.decode import decode_expr, Instr


WASM_MAGIC   = b"\x00asm"
WASM_VERSION = b"\x01\x00\x00\x00"


# ── Module section data classes ─────────────────────────────────────────────

@dataclass
class ImportDesc:
    kind:        str    # "func" | "table" | "mem" | "global"
    type_idx:    int | None = None
    table_type:  TableType | None = None
    mem_type:    MemType   | None = None
    global_type: GlobalType | None = None


@dataclass
class Import:
    module: str
    name:   str
    desc:   ImportDesc


@dataclass
class Export:
    name:    str
    kind:    str   # "func" | "table" | "mem" | "global"
    idx:     int


@dataclass
class GlobalDef:
    global_type: GlobalType
    init_expr:   list[Instr]


@dataclass
class ElemSegment:
    mode:       str        # "active" | "passive" | "declarative"
    table_idx:  int
    offset_expr: list[Instr] | None
    elem_type:  ValType
    init:       list[list[Instr]]   # list of const expressions (or func indices)
    func_indices: list[int] | None  # legacy encoding


@dataclass
class DataSegment:
    mode:       str        # "active" | "passive"
    mem_idx:    int
    offset_expr: list[Instr] | None
    data:        bytes


@dataclass
class LocalGroup:
    count:    int
    val_type: ValType


@dataclass
class FuncBody:
    locals:  list[LocalGroup]
    code:    list[Instr]


@dataclass
class WasmModule:
    types:     list[FuncType]     = field(default_factory=list)
    imports:   list[Import]       = field(default_factory=list)
    func_types: list[int]         = field(default_factory=list)  # type indices
    tables:    list[TableType]    = field(default_factory=list)
    mems:      list[MemType]      = field(default_factory=list)
    globals_:  list[GlobalDef]    = field(default_factory=list)
    exports:   list[Export]       = field(default_factory=list)
    start:     int | None         = None
    elems:     list[ElemSegment]  = field(default_factory=list)
    codes:     list[FuncBody]     = field(default_factory=list)
    datas:     list[DataSegment]  = field(default_factory=list)
    customs:   list[tuple[str, bytes]] = field(default_factory=list)

    def n_imported_funcs(self) -> int:
        return sum(1 for i in self.imports if i.desc.kind == "func")

    def n_imported_mems(self) -> int:
        return sum(1 for i in self.imports if i.desc.kind == "mem")

    def n_imported_globals(self) -> int:
        return sum(1 for i in self.imports if i.desc.kind == "global")

    def n_imported_tables(self) -> int:
        return sum(1 for i in self.imports if i.desc.kind == "table")

    def total_funcs(self) -> int:
        return self.n_imported_funcs() + len(self.func_types)

    def func_type(self, func_idx: int) -> FuncType:
        n_imp = self.n_imported_funcs()
        if func_idx < n_imp:
            return self.types[self.imports[func_idx].desc.type_idx]
        local_idx = func_idx - n_imp
        return self.types[self.func_types[local_idx]]


# ── Section parsers ─────────────────────────────────────────────────────────

def _parse_type_section(r: BinaryReader) -> list[FuncType]:
    return [read_func_type(r) for _ in range(r.read_u32())]


def _parse_import_section(r: BinaryReader) -> list[Import]:
    imports = []
    for _ in range(r.read_u32()):
        mod  = r.read_name()
        name = r.read_name()
        kind = r.read_byte()
        if kind == 0x00:
            desc = ImportDesc(kind="func", type_idx=r.read_u32())
        elif kind == 0x01:
            desc = ImportDesc(kind="table", table_type=read_table_type(r))
        elif kind == 0x02:
            desc = ImportDesc(kind="mem", mem_type=read_mem_type(r))
        elif kind == 0x03:
            desc = ImportDesc(kind="global", global_type=read_global_type(r))
        else:
            raise ValueError(f"Unknown import kind 0x{kind:02x}")
        imports.append(Import(mod, name, desc))
    return imports


def _parse_func_section(r: BinaryReader) -> list[int]:
    return [r.read_u32() for _ in range(r.read_u32())]


def _parse_table_section(r: BinaryReader) -> list[TableType]:
    return [read_table_type(r) for _ in range(r.read_u32())]


def _parse_mem_section(r: BinaryReader) -> list[MemType]:
    return [read_mem_type(r) for _ in range(r.read_u32())]


def _parse_global_section(r: BinaryReader) -> list[GlobalDef]:
    defs = []
    for _ in range(r.read_u32()):
        gt   = read_global_type(r)
        expr = decode_expr(r)
        defs.append(GlobalDef(gt, expr))
    return defs


def _parse_export_section(r: BinaryReader) -> list[Export]:
    kinds = {0: "func", 1: "table", 2: "mem", 3: "global"}
    exports = []
    for _ in range(r.read_u32()):
        name = r.read_name()
        k    = r.read_byte()
        idx  = r.read_u32()
        exports.append(Export(name, kinds.get(k, f"unknown_{k}"), idx))
    return exports


def _parse_element_section(r: BinaryReader) -> list[ElemSegment]:
    segs = []
    for _ in range(r.read_u32()):
        seg_type = r.read_u32()

        # Legacy format (seg_type == 0): active segment, implicit table 0
        if seg_type == 0:
            offset = decode_expr(r)
            n      = r.read_u32()
            fi     = [r.read_u32() for _ in range(n)]
            segs.append(ElemSegment("active", 0, offset, ValType.FUNCREF, [], fi))

        elif seg_type == 1:
            r.read_byte()  # elemkind
            n  = r.read_u32()
            fi = [r.read_u32() for _ in range(n)]
            segs.append(ElemSegment("passive", 0, None, ValType.FUNCREF, [], fi))

        elif seg_type == 2:
            tidx   = r.read_u32()
            offset = decode_expr(r)
            r.read_byte()  # elemkind
            n  = r.read_u32()
            fi = [r.read_u32() for _ in range(n)]
            segs.append(ElemSegment("active", tidx, offset, ValType.FUNCREF, [], fi))

        elif seg_type == 4:
            offset = decode_expr(r)
            n    = r.read_u32()
            init = [decode_expr(r) for _ in range(n)]
            segs.append(ElemSegment("active", 0, offset, ValType.FUNCREF, init, None))

        else:
            # Remaining formats: skip gracefully
            segs.append(ElemSegment("passive", 0, None, ValType.FUNCREF, [], None))

    return segs


def _parse_code_section(r: BinaryReader) -> list[FuncBody]:
    bodies = []
    for _ in range(r.read_u32()):
        size  = r.read_u32()
        sub   = r.sub_reader(size)
        n_lg  = sub.read_u32()
        lgs   = []
        for _ in range(n_lg):
            count = sub.read_u32()
            vt    = read_val_type(sub)
            lgs.append(LocalGroup(count, vt))
        code = decode_expr(sub)
        bodies.append(FuncBody(lgs, code))
    return bodies


def _parse_data_section(r: BinaryReader) -> list[DataSegment]:
    segs = []
    for _ in range(r.read_u32()):
        seg_type = r.read_u32()
        if seg_type == 0:
            offset = decode_expr(r)
            n      = r.read_u32()
            data   = r.slice(n)
            segs.append(DataSegment("active", 0, offset, data))
        elif seg_type == 1:
            n    = r.read_u32()
            data = r.slice(n)
            segs.append(DataSegment("passive", 0, None, data))
        elif seg_type == 2:
            midx   = r.read_u32()
            offset = decode_expr(r)
            n      = r.read_u32()
            data   = r.slice(n)
            segs.append(DataSegment("active", midx, offset, data))
        else:
            n    = r.read_u32()
            data = r.slice(n)
            segs.append(DataSegment("passive", 0, None, data))
    return segs


# ── Top-level parser ────────────────────────────────────────────────────────

def parse(data: bytes) -> WasmModule:
    r = BinaryReader(data)

    magic   = r.slice(4)
    version = r.slice(4)
    if magic != WASM_MAGIC:
        raise ValueError(f"Not a wasm binary (magic = {magic.hex()})")
    if version != WASM_VERSION:
        raise ValueError(f"Unsupported wasm version {version.hex()}")

    mod = WasmModule()

    _PARSERS = {
        1:  ("types",    _parse_type_section),
        2:  ("imports",  _parse_import_section),
        3:  ("ftypes",   _parse_func_section),
        4:  ("tables",   _parse_table_section),
        5:  ("mems",     _parse_mem_section),
        6:  ("globals_", _parse_global_section),
        7:  ("exports",  _parse_export_section),
        9:  ("elems",    _parse_element_section),
        10: ("codes",    _parse_code_section),
        11: ("datas",    _parse_data_section),
    }

    while not r.eof():
        sec_id   = r.read_byte()
        sec_size = r.read_u32()
        sec_r    = r.sub_reader(sec_size)

        if sec_id == 0:
            name = sec_r.read_name()
            rest = sec_r.slice(sec_r.remaining)
            mod.customs.append((name, rest))
        elif sec_id == 8:
            mod.start = sec_r.read_u32()
        elif sec_id == 12:
            sec_r.read_u32()  # data count — consumed but not stored separately
        elif sec_id in _PARSERS:
            attr, fn = _PARSERS[sec_id]
            if attr == "ftypes":
                mod.func_types = fn(sec_r)
            else:
                setattr(mod, attr, fn(sec_r))
        # Unknown section IDs are silently skipped

    return mod
