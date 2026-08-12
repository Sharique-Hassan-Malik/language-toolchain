"""
WebAssembly module instantiation.

Takes a parsed WasmModule and:
  1. Allocates memory, tables and globals
  2. Resolves imports against the provided host environment
  3. Initialises data segments and element segments
  4. Exposes a clean call() / get_export() API

Reference: https://webassembly.github.io/spec/core/exec/modules.html
"""

from __future__ import annotations

import struct
from typing import Any, Callable

from wasm.executor import Executor, HostFunc, _i32, _u32, _default, _Return
from wasm.memory import Memory
from wasm.parser import WasmModule
from wasm.types import ValType


class WasmError(Exception):
    pass


class ModuleInstance:
    def __init__(
        self,
        module:  WasmModule,
        imports: dict[str, dict[str, Any]] | None = None,
    ):
        self.module  = module
        self._exec   = Executor(self)

        # ── imports ──────────────────────────────────────────────────────
        imports = imports or {}
        self.funcs:   list             = []
        self.mems:    list[Memory]     = []
        self.tables:  list[list]       = []
        self.globals_: list[Any]       = []

        for imp in module.imports:
            mod_env = imports.get(imp.module, {})
            if imp.name not in mod_env:
                # Provide a stub that raises at call time
                val = _make_stub(imp)
            else:
                val = mod_env[imp.name]

            kind = imp.desc.kind
            if kind == "func":
                ft = module.types[imp.desc.type_idx]
                if callable(val):
                    self.funcs.append(HostFunc(ft, val))
                else:
                    self.funcs.append(val)
            elif kind == "mem":
                self.mems.append(val if isinstance(val, Memory) else Memory())
            elif kind == "table":
                self.tables.append(val if isinstance(val, list) else [])
            elif kind == "global":
                self.globals_.append(val)

        # ── local memory ─────────────────────────────────────────────────
        for mt in module.mems:
            mem = Memory(mt.limits.min, mt.limits.max)
            self.mems.append(mem)

        # ── local tables ─────────────────────────────────────────────────
        for tt in module.tables:
            size  = tt.limits.min
            table = [None] * size
            self.tables.append(table)

        # ── local globals ─────────────────────────────────────────────────
        for gd in module.globals_:
            val = self._eval_const_expr(gd.init_expr)
            self.globals_.append(val)

        # ── data segments ─────────────────────────────────────────────────
        for ds in module.datas:
            if ds.mode == "active":
                mem_idx = ds.mem_idx
                offset  = int(self._eval_const_expr(ds.offset_expr))
                mem     = self._mem(mem_idx)
                mem.write_bytes(offset, ds.data)

        # ── element segments ──────────────────────────────────────────────
        for es in module.elems:
            if es.mode != "active":
                continue
            table   = self.tables[es.table_idx]
            offset  = int(self._eval_const_expr(es.offset_expr)) if es.offset_expr else 0
            indices = es.func_indices or []
            for j, fi in enumerate(indices):
                idx = offset + j
                if idx < len(table):
                    table[idx] = fi

        # ── start function ────────────────────────────────────────────────
        if module.start is not None:
            self._exec.call(module.start, [])

        # convenience reference
        self.mem = self.mems[0] if self.mems else None

    # ── public API ─────────────────────────────────────────────────────────

    def call(self, func_name: str, *args) -> list:
        """Call an exported function by name."""
        idx = self._export_idx("func", func_name)
        try:
            return self._exec.call(idx, list(args))
        except _Return as r:
            ft = self.module.func_type(idx)
            return r.values[-len(ft.results):] if ft.results else []

    def call_idx(self, func_idx: int, *args) -> list:
        return self._exec.call(func_idx, list(args))

    def get_export(self, name: str) -> Any:
        for exp in self.module.exports:
            if exp.name == name:
                if exp.kind == "mem":
                    return self.mems[exp.idx]
                if exp.kind == "global":
                    return self.globals_[exp.idx]
                if exp.kind == "table":
                    return self.tables[exp.idx]
                if exp.kind == "func":
                    return exp.idx
        raise KeyError(f"export {name!r} not found")

    def exports(self) -> dict[str, str]:
        return {e.name: e.kind for e in self.module.exports}

    # ── helpers ────────────────────────────────────────────────────────────

    def _mem(self, idx: int = 0) -> Memory:
        if not self.mems:
            raise WasmError("no memory in module")
        return self.mems[idx]

    def _export_idx(self, kind: str, name: str) -> int:
        for exp in self.module.exports:
            if exp.name == name and exp.kind == kind:
                return exp.idx
        raise KeyError(f"no exported {kind} named {name!r}")

    def _eval_const_expr(self, instrs: list) -> Any:
        """Evaluate a constant expression (global init, data offset, etc.)."""
        from wasm.instructions.decode import I32_CONST, I64_CONST, F32_CONST, F64_CONST, GLOBAL_GET, END
        for instr in instrs:
            o = instr.opcode
            if o == I32_CONST:
                return instr.imm
            if o == I64_CONST:
                return instr.imm
            if o == F32_CONST:
                return instr.imm
            if o == F64_CONST:
                return instr.imm
            if o == GLOBAL_GET:
                return self.globals_[instr.imm]
            if o == END:
                return 0
        return 0


def _make_stub(imp) -> Any:
    name = f"{imp.module}.{imp.name}"
    if imp.desc.kind == "func":
        def stub(*args):
            raise WasmError(f"unresolved import: {name}")
        return stub
    return None
