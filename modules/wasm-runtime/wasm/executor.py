"""
WebAssembly stack machine executor.

Implements the complete MVP instruction set. The interpreter uses a Python list
as the operand stack and a separate list of label frames for structured control
flow (block/loop/if/br/br_table/return).

Design notes:
  - Integer values are Python ints (arbitrary precision, masked to 32/64 bits)
  - Float values are Python floats (64-bit doubles; f32 operations round through struct)
  - Locals and globals are plain Python lists
  - The call stack is implemented via recursive Python calls to _exec_func
  - Block frames track the stack depth at block entry for branch-on-exit cleanup

Reference: https://webassembly.github.io/spec/core/exec/instructions.html
"""

from __future__ import annotations

import math
import struct
from typing import Any, Callable

from wasm.instructions import decode as op
from wasm.memory import Memory, _i32, _i64
from wasm.types import ValType


# ── Sentinel signals for structured control flow ───────────────────────────

class _Return(Exception):
    def __init__(self, values: list): self.values = values

class _Break(Exception):
    def __init__(self, depth: int): self.depth = depth


# ── Frame (block context) ──────────────────────────────────────────────────

class _Frame:
    __slots__ = ("kind", "stack_depth", "arity", "loop_instrs")

    def __init__(self, kind: str, stack_depth: int, arity: int, loop_instrs=None):
        self.kind        = kind          # "block" | "loop" | "if"
        self.stack_depth = stack_depth
        self.arity       = arity
        self.loop_instrs = loop_instrs   # not None for loops (for re-entry)


# ── Host function wrapper ──────────────────────────────────────────────────

class HostFunc:
    def __init__(self, func_type, fn: Callable):
        self.func_type = func_type
        self.fn        = fn


# ── Executor ──────────────────────────────────────────────────────────────

class Executor:
    def __init__(self, instance):
        self.inst = instance   # ModuleInstance

    # ── public entry point ────────────────────────────────────────────────

    def call(self, func_idx: int, args: list) -> list:
        ft = self.inst.module.func_type(func_idx)
        n_imp = self.inst.module.n_imported_funcs()

        if func_idx < n_imp:
            hf = self.inst.funcs[func_idx]
            result = hf.fn(*args)
            if result is None:
                return []
            return list(result) if isinstance(result, (list, tuple)) else [result]

        body      = self.inst.module.codes[func_idx - n_imp]
        local_vals = list(args) + [_default(lt) for lg in body.locals for lt in [lg.val_type] * lg.count]
        stack: list = []
        self._exec(body.code, stack, local_vals)
        n_res = len(ft.results)
        return stack[-n_res:] if n_res else []

    # ── instruction dispatch ──────────────────────────────────────────────

    def _exec(self, instrs: list, stack: list, local_vals: list) -> None:
        i = 0
        while i < len(instrs):
            instr = instrs[i]
            o     = instr.opcode

            # ── control ──────────────────────────────────────────────────

            if o == op.NOP:
                pass

            elif o == op.UNREACHABLE:
                raise RuntimeError("wasm: unreachable executed")

            elif o == op.BLOCK:
                arity   = _block_arity(instr.imm, self.inst.module)
                inner   = _collect_block(instrs, i + 1)
                n_inner = len(inner)
                try:
                    self._exec(inner, stack, local_vals)
                except _Break as br:
                    if br.depth > 0:
                        raise _Break(br.depth - 1)
                    # break to here — keep arity results
                    _trim_stack(stack, len(stack) - arity)
                i += n_inner + 2  # skip body + END
                continue

            elif o == op.LOOP:
                inner   = _collect_block(instrs, i + 1)
                n_inner = len(inner)
                while True:
                    try:
                        self._exec(inner, stack, local_vals)
                        break
                    except _Break as br:
                        if br.depth == 0:
                            continue   # br 0 in loop = re-enter
                        raise _Break(br.depth - 1)
                i += n_inner + 2
                continue

            elif o == op.IF:
                arity   = _block_arity(instr.imm, self.inst.module)
                cond    = stack.pop()
                then_b, else_b, skip = _collect_if(instrs, i + 1)
                branch  = then_b if cond else else_b
                try:
                    self._exec(branch, stack, local_vals)
                except _Break as br:
                    if br.depth > 0:
                        raise _Break(br.depth - 1)
                    _trim_stack(stack, len(stack) - arity)
                # Past the matching END, not onto it. Landing on the END made
                # the dispatch loop `break`, so every instruction after an `if`
                # was silently discarded — a function returned whatever it had
                # before the branch. BLOCK and LOOP already skip body + END; IF
                # now does the same.
                i += skip + 2
                continue

            elif o == op.BR:
                raise _Break(instr.imm)

            elif o == op.BR_IF:
                if stack.pop():
                    raise _Break(instr.imm)

            elif o == op.BR_TABLE:
                targets, default = instr.imm
                idx = stack.pop()
                depth = targets[idx] if idx < len(targets) else default
                raise _Break(depth)

            elif o == op.RETURN:
                raise _Return(stack[:])

            elif o == op.CALL:
                self._do_call(instr.imm, stack)

            elif o == op.CALL_INDIRECT:
                type_idx, table_idx = instr.imm
                elem_idx = stack.pop()
                table    = self.inst.tables[table_idx]
                if elem_idx >= len(table) or table[elem_idx] is None:
                    raise RuntimeError(f"wasm: call_indirect: null or out-of-bounds table element {elem_idx}")
                func_idx = table[elem_idx]
                # Type check
                expected = self.inst.module.types[type_idx]
                actual   = self.inst.module.func_type(func_idx)
                if expected != actual:
                    raise RuntimeError(f"wasm: call_indirect: type mismatch {expected} != {actual}")
                self._do_call(func_idx, stack)

            # ── parametric ───────────────────────────────────────────────

            elif o == op.DROP:
                stack.pop()

            elif o == op.SELECT or o == op.SELECT_T:
                c = stack.pop(); b = stack.pop(); a = stack.pop()
                stack.append(a if c else b)

            # ── locals / globals ─────────────────────────────────────────

            elif o == op.LOCAL_GET:
                stack.append(local_vals[instr.imm])

            elif o == op.LOCAL_SET:
                local_vals[instr.imm] = stack.pop()

            elif o == op.LOCAL_TEE:
                local_vals[instr.imm] = stack[-1]

            elif o == op.GLOBAL_GET:
                stack.append(self.inst.globals_[instr.imm])

            elif o == op.GLOBAL_SET:
                self.inst.globals_[instr.imm] = stack.pop()

            # ── memory ───────────────────────────────────────────────────

            elif o == op.I32_LOAD:
                a = stack.pop(); stack.append(self.inst.mem.load_i32(a, instr.imm.offset))
            elif o == op.I64_LOAD:
                a = stack.pop(); stack.append(self.inst.mem.load_i64(a, instr.imm.offset))
            elif o == op.F32_LOAD:
                a = stack.pop(); stack.append(self.inst.mem.load_f32(a, instr.imm.offset))
            elif o == op.F64_LOAD:
                a = stack.pop(); stack.append(self.inst.mem.load_f64(a, instr.imm.offset))
            elif o == op.I32_LOAD8_S:
                a = stack.pop(); stack.append(_i32(self.inst.mem.load_i8_s(a, instr.imm.offset)))
            elif o == op.I32_LOAD8_U:
                a = stack.pop(); stack.append(self.inst.mem.load_i8_u(a, instr.imm.offset))
            elif o == op.I32_LOAD16_S:
                a = stack.pop(); stack.append(_i32(self.inst.mem.load_i16_s(a, instr.imm.offset)))
            elif o == op.I32_LOAD16_U:
                a = stack.pop(); stack.append(self.inst.mem.load_i16_u(a, instr.imm.offset))
            elif o == op.I64_LOAD8_S:
                a = stack.pop(); stack.append(self.inst.mem.load_i8_s(a, instr.imm.offset))
            elif o == op.I64_LOAD8_U:
                a = stack.pop(); stack.append(self.inst.mem.load_i8_u(a, instr.imm.offset))
            elif o == op.I64_LOAD16_S:
                a = stack.pop(); stack.append(self.inst.mem.load_i16_s(a, instr.imm.offset))
            elif o == op.I64_LOAD16_U:
                a = stack.pop(); stack.append(self.inst.mem.load_i16_u(a, instr.imm.offset))
            elif o == op.I64_LOAD32_S:
                a = stack.pop(); stack.append(self.inst.mem.load_i32_s(a, instr.imm.offset))
            elif o == op.I64_LOAD32_U:
                a = stack.pop(); stack.append(self.inst.mem.load_i32_u(a, instr.imm.offset))
            elif o == op.I32_STORE:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i32(a, v, instr.imm.offset)
            elif o == op.I64_STORE:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i64(a, v, instr.imm.offset)
            elif o == op.F32_STORE:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_f32(a, v, instr.imm.offset)
            elif o == op.F64_STORE:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_f64(a, v, instr.imm.offset)
            elif o == op.I32_STORE8:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i8(a, v, instr.imm.offset)
            elif o == op.I32_STORE16:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i16(a, v, instr.imm.offset)
            elif o == op.I64_STORE8:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i8(a, v, instr.imm.offset)
            elif o == op.I64_STORE16:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i16(a, v, instr.imm.offset)
            elif o == op.I64_STORE32:
                v = stack.pop(); a = stack.pop(); self.inst.mem.store_i32(a, v, instr.imm.offset)
            elif o == op.MEMORY_SIZE:
                stack.append(self.inst.mem.size)
            elif o == op.MEMORY_GROW:
                delta = stack.pop()
                stack.append(self.inst.mem.grow(delta))

            # ── constants ────────────────────────────────────────────────

            elif o == op.I32_CONST:
                stack.append(instr.imm)
            elif o == op.I64_CONST:
                stack.append(instr.imm)
            elif o == op.F32_CONST:
                stack.append(instr.imm)
            elif o == op.F64_CONST:
                stack.append(instr.imm)

            # ── i32 comparisons ──────────────────────────────────────────

            elif o == op.I32_EQZ: stack.append(int(stack.pop() == 0))
            elif o == op.I32_EQ:  b=stack.pop(); a=stack.pop(); stack.append(int(a==b))
            elif o == op.I32_NE:  b=stack.pop(); a=stack.pop(); stack.append(int(a!=b))
            elif o == op.I32_LT_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i32(a) < _i32(b)))
            elif o == op.I32_LT_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u32(a) < _u32(b)))
            elif o == op.I32_GT_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i32(a) > _i32(b)))
            elif o == op.I32_GT_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u32(a) > _u32(b)))
            elif o == op.I32_LE_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i32(a) <= _i32(b)))
            elif o == op.I32_LE_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u32(a) <= _u32(b)))
            elif o == op.I32_GE_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i32(a) >= _i32(b)))
            elif o == op.I32_GE_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u32(a) >= _u32(b)))

            # ── i64 comparisons ──────────────────────────────────────────

            elif o == op.I64_EQZ: stack.append(int(stack.pop() == 0))
            elif o == op.I64_EQ:  b=stack.pop(); a=stack.pop(); stack.append(int(a==b))
            elif o == op.I64_NE:  b=stack.pop(); a=stack.pop(); stack.append(int(a!=b))
            elif o == op.I64_LT_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i64(a) < _i64(b)))
            elif o == op.I64_LT_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u64(a) < _u64(b)))
            elif o == op.I64_GT_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i64(a) > _i64(b)))
            elif o == op.I64_GT_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u64(a) > _u64(b)))
            elif o == op.I64_LE_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i64(a) <= _i64(b)))
            elif o == op.I64_LE_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u64(a) <= _u64(b)))
            elif o == op.I64_GE_S: b=stack.pop(); a=stack.pop(); stack.append(int(_i64(a) >= _i64(b)))
            elif o == op.I64_GE_U: b=stack.pop(); a=stack.pop(); stack.append(int(_u64(a) >= _u64(b)))

            # ── f32/f64 comparisons ───────────────────────────────────────

            elif o == op.F32_EQ: b=stack.pop(); a=stack.pop(); stack.append(int(a==b))
            elif o == op.F32_NE: b=stack.pop(); a=stack.pop(); stack.append(int(a!=b))
            elif o == op.F32_LT: b=stack.pop(); a=stack.pop(); stack.append(int(a<b))
            elif o == op.F32_GT: b=stack.pop(); a=stack.pop(); stack.append(int(a>b))
            elif o == op.F32_LE: b=stack.pop(); a=stack.pop(); stack.append(int(a<=b))
            elif o == op.F32_GE: b=stack.pop(); a=stack.pop(); stack.append(int(a>=b))
            elif o == op.F64_EQ: b=stack.pop(); a=stack.pop(); stack.append(int(a==b))
            elif o == op.F64_NE: b=stack.pop(); a=stack.pop(); stack.append(int(a!=b))
            elif o == op.F64_LT: b=stack.pop(); a=stack.pop(); stack.append(int(a<b))
            elif o == op.F64_GT: b=stack.pop(); a=stack.pop(); stack.append(int(a>b))
            elif o == op.F64_LE: b=stack.pop(); a=stack.pop(); stack.append(int(a<=b))
            elif o == op.F64_GE: b=stack.pop(); a=stack.pop(); stack.append(int(a>=b))

            # ── i32 arithmetic ────────────────────────────────────────────

            elif o == op.I32_CLZ:    stack.append(_clz32(stack.pop()))
            elif o == op.I32_CTZ:    stack.append(_ctz32(stack.pop()))
            elif o == op.I32_POPCNT: stack.append(bin(_u32(stack.pop())).count("1"))
            elif o == op.I32_ADD:    b=stack.pop(); a=stack.pop(); stack.append(_i32(a+b))
            elif o == op.I32_SUB:    b=stack.pop(); a=stack.pop(); stack.append(_i32(a-b))
            elif o == op.I32_MUL:    b=stack.pop(); a=stack.pop(); stack.append(_i32(a*b))
            elif o == op.I32_DIV_S:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i32.div_s division by zero")
                stack.append(_i32(int(_i32(a) / _i32(b))))
            elif o == op.I32_DIV_U:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i32.div_u division by zero")
                stack.append(_u32(a) // _u32(b))
            elif o == op.I32_REM_S:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i32.rem_s division by zero")
                stack.append(_i32(_i32(a) % _i32(b)))
            elif o == op.I32_REM_U:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i32.rem_u division by zero")
                stack.append(_u32(a) % _u32(b))
            elif o == op.I32_AND:    b=stack.pop(); a=stack.pop(); stack.append(_i32(a&b))
            elif o == op.I32_OR:     b=stack.pop(); a=stack.pop(); stack.append(_i32(a|b))
            elif o == op.I32_XOR:    b=stack.pop(); a=stack.pop(); stack.append(_i32(a^b))
            elif o == op.I32_SHL:    b=stack.pop(); a=stack.pop(); stack.append(_i32(_u32(a) << (_u32(b) & 31)))
            elif o == op.I32_SHR_S:  b=stack.pop(); a=stack.pop(); stack.append(_i32(_i32(a) >> (_u32(b) & 31)))
            elif o == op.I32_SHR_U:  b=stack.pop(); a=stack.pop(); stack.append(_u32(a) >> (_u32(b) & 31))
            elif o == op.I32_ROTL:   b=stack.pop(); a=stack.pop(); stack.append(_rotl32(_u32(a), _u32(b) & 31))
            elif o == op.I32_ROTR:   b=stack.pop(); a=stack.pop(); stack.append(_rotr32(_u32(a), _u32(b) & 31))

            # ── i64 arithmetic ────────────────────────────────────────────

            elif o == op.I64_CLZ:    stack.append(_clz64(stack.pop()))
            elif o == op.I64_CTZ:    stack.append(_ctz64(stack.pop()))
            elif o == op.I64_POPCNT: stack.append(bin(_u64(stack.pop())).count("1"))
            elif o == op.I64_ADD:    b=stack.pop(); a=stack.pop(); stack.append(_i64(a+b))
            elif o == op.I64_SUB:    b=stack.pop(); a=stack.pop(); stack.append(_i64(a-b))
            elif o == op.I64_MUL:    b=stack.pop(); a=stack.pop(); stack.append(_i64(a*b))
            elif o == op.I64_DIV_S:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i64.div_s division by zero")
                stack.append(_i64(int(_i64(a)/_i64(b))))
            elif o == op.I64_DIV_U:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i64.div_u division by zero")
                stack.append(_u64(a) // _u64(b))
            elif o == op.I64_REM_S:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i64.rem_s division by zero")
                stack.append(_i64(_i64(a) % _i64(b)))
            elif o == op.I64_REM_U:
                b=stack.pop(); a=stack.pop()
                if b == 0: raise RuntimeError("wasm: i64.rem_u division by zero")
                stack.append(_u64(a) % _u64(b))
            elif o == op.I64_AND:    b=stack.pop(); a=stack.pop(); stack.append(_i64(a&b))
            elif o == op.I64_OR:     b=stack.pop(); a=stack.pop(); stack.append(_i64(a|b))
            elif o == op.I64_XOR:    b=stack.pop(); a=stack.pop(); stack.append(_i64(a^b))
            elif o == op.I64_SHL:    b=stack.pop(); a=stack.pop(); stack.append(_i64(_u64(a) << (_u64(b) & 63)))
            elif o == op.I64_SHR_S:  b=stack.pop(); a=stack.pop(); stack.append(_i64(_i64(a) >> (_u64(b) & 63)))
            elif o == op.I64_SHR_U:  b=stack.pop(); a=stack.pop(); stack.append(_u64(a) >> (_u64(b) & 63))
            elif o == op.I64_ROTL:   b=stack.pop(); a=stack.pop(); stack.append(_rotl64(_u64(a), _u64(b) & 63))
            elif o == op.I64_ROTR:   b=stack.pop(); a=stack.pop(); stack.append(_rotr64(_u64(a), _u64(b) & 63))

            # ── f32 / f64 arithmetic ──────────────────────────────────────

            elif o == op.F32_ABS:     stack.append(abs(stack.pop()))
            elif o == op.F32_NEG:     stack.append(-stack.pop())
            elif o == op.F32_CEIL:    stack.append(_f32(math.ceil(stack.pop())))
            elif o == op.F32_FLOOR:   stack.append(_f32(math.floor(stack.pop())))
            elif o == op.F32_TRUNC:   stack.append(_f32(math.trunc(stack.pop())))
            elif o == op.F32_NEAREST: stack.append(_f32(_nearest(stack.pop())))
            elif o == op.F32_SQRT:    stack.append(_f32(math.sqrt(stack.pop())))
            elif o == op.F32_ADD:     b=stack.pop(); a=stack.pop(); stack.append(_f32(a+b))
            elif o == op.F32_SUB:     b=stack.pop(); a=stack.pop(); stack.append(_f32(a-b))
            elif o == op.F32_MUL:     b=stack.pop(); a=stack.pop(); stack.append(_f32(a*b))
            elif o == op.F32_DIV:     b=stack.pop(); a=stack.pop(); stack.append(_f32(a/b) if b else (math.copysign(math.inf, a*b) if a else float("nan")))
            elif o == op.F32_MIN:     b=stack.pop(); a=stack.pop(); stack.append(_f32(_fmin(a,b)))
            elif o == op.F32_MAX:     b=stack.pop(); a=stack.pop(); stack.append(_f32(_fmax(a,b)))
            elif o == op.F32_COPYSIGN: b=stack.pop(); a=stack.pop(); stack.append(_f32(math.copysign(a,b)))
            elif o == op.F64_ABS:     stack.append(abs(stack.pop()))
            elif o == op.F64_NEG:     stack.append(-stack.pop())
            elif o == op.F64_CEIL:    stack.append(math.ceil(stack.pop()))
            elif o == op.F64_FLOOR:   stack.append(math.floor(stack.pop()))
            elif o == op.F64_TRUNC:   stack.append(float(math.trunc(stack.pop())))
            elif o == op.F64_NEAREST: stack.append(_nearest(stack.pop()))
            elif o == op.F64_SQRT:    stack.append(math.sqrt(stack.pop()))
            elif o == op.F64_ADD:     b=stack.pop(); a=stack.pop(); stack.append(a+b)
            elif o == op.F64_SUB:     b=stack.pop(); a=stack.pop(); stack.append(a-b)
            elif o == op.F64_MUL:     b=stack.pop(); a=stack.pop(); stack.append(a*b)
            elif o == op.F64_DIV:     b=stack.pop(); a=stack.pop(); stack.append(a/b if b else (math.copysign(math.inf,a*b) if a else float("nan")))
            elif o == op.F64_MIN:     b=stack.pop(); a=stack.pop(); stack.append(_fmin(a,b))
            elif o == op.F64_MAX:     b=stack.pop(); a=stack.pop(); stack.append(_fmax(a,b))
            elif o == op.F64_COPYSIGN: b=stack.pop(); a=stack.pop(); stack.append(math.copysign(a,b))

            # ── conversions ───────────────────────────────────────────────

            elif o == op.I32_WRAP_I64:      stack.append(_i32(stack.pop()))
            elif o == op.I32_TRUNC_F32_S:   stack.append(_i32(int(math.trunc(stack.pop()))))
            elif o == op.I32_TRUNC_F32_U:   stack.append(_u32(int(math.trunc(stack.pop()))))
            elif o == op.I32_TRUNC_F64_S:   stack.append(_i32(int(math.trunc(stack.pop()))))
            elif o == op.I32_TRUNC_F64_U:   stack.append(_u32(int(math.trunc(stack.pop()))))
            elif o == op.I64_EXTEND_I32_S:  stack.append(_i64(_i32(stack.pop())))
            elif o == op.I64_EXTEND_I32_U:  stack.append(_u32(stack.pop()))
            elif o == op.I64_TRUNC_F32_S:   stack.append(_i64(int(math.trunc(stack.pop()))))
            elif o == op.I64_TRUNC_F32_U:   stack.append(_u64(int(math.trunc(stack.pop()))))
            elif o == op.I64_TRUNC_F64_S:   stack.append(_i64(int(math.trunc(stack.pop()))))
            elif o == op.I64_TRUNC_F64_U:   stack.append(_u64(int(math.trunc(stack.pop()))))
            elif o == op.F32_CONVERT_I32_S: stack.append(_f32(float(_i32(stack.pop()))))
            elif o == op.F32_CONVERT_I32_U: stack.append(_f32(float(_u32(stack.pop()))))
            elif o == op.F32_CONVERT_I64_S: stack.append(_f32(float(_i64(stack.pop()))))
            elif o == op.F32_CONVERT_I64_U: stack.append(_f32(float(_u64(stack.pop()))))
            elif o == op.F32_DEMOTE_F64:    stack.append(_f32(stack.pop()))
            elif o == op.F64_CONVERT_I32_S: stack.append(float(_i32(stack.pop())))
            elif o == op.F64_CONVERT_I32_U: stack.append(float(_u32(stack.pop())))
            elif o == op.F64_CONVERT_I64_S: stack.append(float(_i64(stack.pop())))
            elif o == op.F64_CONVERT_I64_U: stack.append(float(_u64(stack.pop())))
            elif o == op.F64_PROMOTE_F32:   stack.append(float(stack.pop()))
            elif o == op.I32_REINTERPRET_F32:
                stack.append(struct.unpack("<i", struct.pack("<f", stack.pop()))[0])
            elif o == op.I64_REINTERPRET_F64:
                stack.append(struct.unpack("<q", struct.pack("<d", stack.pop()))[0])
            elif o == op.F32_REINTERPRET_I32:
                stack.append(struct.unpack("<f", struct.pack("<i", stack.pop()))[0])
            elif o == op.F64_REINTERPRET_I64:
                stack.append(struct.unpack("<d", struct.pack("<q", stack.pop()))[0])

            # ── sign extension ────────────────────────────────────────────

            elif o == op.I32_EXTEND8_S:  v=stack.pop(); stack.append(_i32((v&0xFF) - 256 if (v&0x80) else (v&0xFF)))
            elif o == op.I32_EXTEND16_S: v=stack.pop(); stack.append(_i32((v&0xFFFF) - 65536 if (v&0x8000) else (v&0xFFFF)))
            elif o == op.I64_EXTEND8_S:  v=stack.pop(); stack.append(_i64((v&0xFF) - 256 if (v&0x80) else (v&0xFF)))
            elif o == op.I64_EXTEND16_S: v=stack.pop(); stack.append(_i64((v&0xFFFF) - 65536 if (v&0x8000) else (v&0xFFFF)))
            elif o == op.I64_EXTEND32_S: v=stack.pop(); stack.append(_i64(_i32(v)))

            elif o == op.END:
                break

            else:
                raise RuntimeError(f"wasm: unimplemented opcode 0x{o:02x}")

            i += 1

    def _do_call(self, func_idx: int, stack: list) -> None:
        ft   = self.inst.module.func_type(func_idx)
        n    = len(ft.params)
        args = stack[-n:] if n else []
        if n:
            del stack[-n:]
        try:
            results = self.call(func_idx, args)
        except _Return as ret:
            results = ret.values[-len(ft.results):] if ft.results else []
        stack.extend(results)


# ── Control flow helpers ───────────────────────────────────────────────────

def _collect_block(instrs: list, start: int) -> list:
    """Return the instruction slice from start up to (not including) the matching END."""
    depth = 0
    j     = start
    while j < len(instrs):
        o = instrs[j].opcode
        if o in (op.BLOCK, op.LOOP, op.IF):
            depth += 1
        elif o == op.END:
            if depth == 0:
                return instrs[start:j]
            depth -= 1
        j += 1
    raise RuntimeError("wasm: unterminated block")


def _collect_if(instrs: list, start: int) -> tuple[list, list, int]:
    """
    Collect then-branch and else-branch from an IF instruction.
    Returns (then_instrs, else_instrs, total_skip_count).
    """
    depth      = 0
    then_b: list = []
    else_b: list = []
    in_else    = False
    j          = start
    while j < len(instrs):
        o = instrs[j].opcode
        if o in (op.BLOCK, op.LOOP, op.IF):
            depth += 1
        elif o == op.ELSE and depth == 0:
            in_else = True
            j += 1
            continue
        elif o == op.END:
            if depth == 0:
                return then_b, else_b, j - start
            depth -= 1
        if in_else:
            else_b.append(instrs[j])
        else:
            then_b.append(instrs[j])
        j += 1
    raise RuntimeError("wasm: unterminated if")


def _block_arity(bt, module) -> int:
    if bt.val_type is None and bt.type_idx is None:
        return 0
    if bt.val_type is not None:
        return 1
    return len(module.types[bt.type_idx].results)


def _trim_stack(stack: list, target_depth: int) -> None:
    """Keep only the bottom target_depth items (the block's result values go on top)."""
    if len(stack) > target_depth:
        del stack[:len(stack) - target_depth]


# ── Numeric helpers ────────────────────────────────────────────────────────

def _u32(v: int) -> int: return v & 0xFFFFFFFF
def _u64(v: int) -> int: return v & 0xFFFFFFFFFFFFFFFF
def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", v))[0]

def _clz32(v: int) -> int:
    v = _u32(v)
    return 32 if v == 0 else 31 - v.bit_length() + 1
def _ctz32(v: int) -> int:
    v = _u32(v)
    if v == 0: return 32
    return (v & -v).bit_length() - 1
def _clz64(v: int) -> int:
    v = _u64(v)
    return 64 if v == 0 else 63 - v.bit_length() + 1
def _ctz64(v: int) -> int:
    v = _u64(v)
    if v == 0: return 64
    return (v & -v).bit_length() - 1
def _rotl32(v: int, n: int) -> int: return _u32((v << n) | (v >> (32 - n))) if n else v
def _rotr32(v: int, n: int) -> int: return _u32((v >> n) | (v << (32 - n))) if n else v
def _rotl64(v: int, n: int) -> int: return _u64((v << n) | (v >> (64 - n))) if n else v
def _rotr64(v: int, n: int) -> int: return _u64((v >> n) | (v << (64 - n))) if n else v

def _nearest(v: float) -> float:
    """Banker's rounding (round half to even) as specified by wasm."""
    if math.isnan(v) or math.isinf(v): return v
    rounded = round(v)
    if abs(v - int(v)) == 0.5 and rounded % 2 != 0:
        rounded -= int(math.copysign(1, v))
    return float(rounded)

def _fmin(a: float, b: float) -> float:
    if math.isnan(a) or math.isnan(b): return float("nan")
    if a == 0.0 and b == 0.0: return math.copysign(0.0, -1.0) if math.copysign(1,a) < 0 or math.copysign(1,b) < 0 else 0.0
    return min(a, b)

def _fmax(a: float, b: float) -> float:
    if math.isnan(a) or math.isnan(b): return float("nan")
    if a == 0.0 and b == 0.0: return 0.0 if math.copysign(1,a) > 0 or math.copysign(1,b) > 0 else math.copysign(0.0,-1.0)
    return max(a, b)


def _default(val_type) -> Any:
    if val_type in (ValType.F32, ValType.F64):
        return 0.0
    return 0
