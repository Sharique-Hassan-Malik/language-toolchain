"""
WebAssembly instruction decoding.

Each instruction is decoded into an `Instr` dataclass carrying the opcode and
any immediate operands. All MVP instructions plus the basic numeric extensions
are supported.

Reference: https://webassembly.github.io/spec/core/binary/instructions.html
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wasm.types import BlockType, read_block_type, ValType


# ── Opcode constants ────────────────────────────────────────────────────────

# Control
UNREACHABLE    = 0x00
NOP            = 0x01
BLOCK          = 0x02
LOOP           = 0x03
IF             = 0x04
ELSE           = 0x05
END            = 0x0B
BR             = 0x0C
BR_IF          = 0x0D
BR_TABLE       = 0x0E
RETURN         = 0x0F
CALL           = 0x10
CALL_INDIRECT  = 0x11

# Reference
REF_NULL       = 0xD0
REF_IS_NULL    = 0xD1
REF_FUNC       = 0xD2

# Parametric
DROP           = 0x1A
SELECT         = 0x1B
SELECT_T       = 0x1C

# Variable
LOCAL_GET      = 0x20
LOCAL_SET      = 0x21
LOCAL_TEE      = 0x22
GLOBAL_GET     = 0x23
GLOBAL_SET     = 0x24

# Table
TABLE_GET      = 0x25
TABLE_SET      = 0x26

# Memory
I32_LOAD       = 0x28
I64_LOAD       = 0x29
F32_LOAD       = 0x2A
F64_LOAD       = 0x2B
I32_LOAD8_S    = 0x2C
I32_LOAD8_U    = 0x2D
I32_LOAD16_S   = 0x2E
I32_LOAD16_U   = 0x2F
I64_LOAD8_S    = 0x30
I64_LOAD8_U    = 0x31
I64_LOAD16_S   = 0x32
I64_LOAD16_U   = 0x33
I64_LOAD32_S   = 0x34
I64_LOAD32_U   = 0x35
I32_STORE      = 0x36
I64_STORE      = 0x37
F32_STORE      = 0x38
F64_STORE      = 0x39
I32_STORE8     = 0x3A
I32_STORE16    = 0x3B
I64_STORE8     = 0x3C
I64_STORE16    = 0x3D
I64_STORE32    = 0x3E
MEMORY_SIZE    = 0x3F
MEMORY_GROW    = 0x40

# i32 constants and arithmetic
I32_CONST      = 0x41
I64_CONST      = 0x42
F32_CONST      = 0x43
F64_CONST      = 0x44

I32_EQZ        = 0x45
I32_EQ         = 0x46
I32_NE         = 0x47
I32_LT_S       = 0x48
I32_LT_U       = 0x49
I32_GT_S       = 0x4A
I32_GT_U       = 0x4B
I32_LE_S       = 0x4C
I32_LE_U       = 0x4D
I32_GE_S       = 0x4E
I32_GE_U       = 0x4F

I64_EQZ        = 0x50
I64_EQ         = 0x51
I64_NE         = 0x52
I64_LT_S       = 0x53
I64_LT_U       = 0x54
I64_GT_S       = 0x55
I64_GT_U       = 0x56
I64_LE_S       = 0x57
I64_LE_U       = 0x58
I64_GE_S       = 0x59
I64_GE_U       = 0x5A

F32_EQ = 0x5B; F32_NE = 0x5C; F32_LT = 0x5D; F32_GT = 0x5E; F32_LE = 0x5F; F32_GE = 0x60
F64_EQ = 0x61; F64_NE = 0x62; F64_LT = 0x63; F64_GT = 0x64; F64_LE = 0x65; F64_GE = 0x66

I32_CLZ        = 0x67
I32_CTZ        = 0x68
I32_POPCNT     = 0x69
I32_ADD        = 0x6A
I32_SUB        = 0x6B
I32_MUL        = 0x6C
I32_DIV_S      = 0x6D
I32_DIV_U      = 0x6E
I32_REM_S      = 0x6F
I32_REM_U      = 0x70
I32_AND        = 0x71
I32_OR         = 0x72
I32_XOR        = 0x73
I32_SHL        = 0x74
I32_SHR_S      = 0x75
I32_SHR_U      = 0x76
I32_ROTL       = 0x77
I32_ROTR       = 0x78

I64_CLZ        = 0x79
I64_CTZ        = 0x7A
I64_POPCNT     = 0x7B
I64_ADD        = 0x7C
I64_SUB        = 0x7D
I64_MUL        = 0x7E
I64_DIV_S      = 0x7F
I64_DIV_U      = 0x80
I64_REM_S      = 0x81
I64_REM_U      = 0x82
I64_AND        = 0x83
I64_OR         = 0x84
I64_XOR        = 0x85
I64_SHL        = 0x86
I64_SHR_S      = 0x87
I64_SHR_U      = 0x88
I64_ROTL       = 0x89
I64_ROTR       = 0x8A

F32_ABS  = 0x8B; F32_NEG  = 0x8C; F32_CEIL = 0x8D; F32_FLOOR = 0x8E
F32_TRUNC = 0x8F; F32_NEAREST = 0x90; F32_SQRT = 0x91
F32_ADD  = 0x92; F32_SUB  = 0x93; F32_MUL  = 0x94; F32_DIV  = 0x95
F32_MIN  = 0x96; F32_MAX  = 0x97; F32_COPYSIGN = 0x98

F64_ABS  = 0x99; F64_NEG  = 0x9A; F64_CEIL = 0x9B; F64_FLOOR = 0x9C
F64_TRUNC = 0x9D; F64_NEAREST = 0x9E; F64_SQRT = 0x9F
F64_ADD  = 0xA0; F64_SUB  = 0xA1; F64_MUL  = 0xA2; F64_DIV  = 0xA3
F64_MIN  = 0xA4; F64_MAX  = 0xA5; F64_COPYSIGN = 0xA6

# Conversions
I32_WRAP_I64       = 0xA7
I32_TRUNC_F32_S    = 0xA8
I32_TRUNC_F32_U    = 0xA9
I32_TRUNC_F64_S    = 0xAA
I32_TRUNC_F64_U    = 0xAB
I64_EXTEND_I32_S   = 0xAC
I64_EXTEND_I32_U   = 0xAD
I64_TRUNC_F32_S    = 0xAE
I64_TRUNC_F32_U    = 0xAF
I64_TRUNC_F64_S    = 0xB0
I64_TRUNC_F64_U    = 0xB1
F32_CONVERT_I32_S  = 0xB2
F32_CONVERT_I32_U  = 0xB3
F32_CONVERT_I64_S  = 0xB4
F32_CONVERT_I64_U  = 0xB5
F32_DEMOTE_F64     = 0xB6
F64_CONVERT_I32_S  = 0xB7
F64_CONVERT_I32_U  = 0xB8
F64_CONVERT_I64_S  = 0xB9
F64_CONVERT_I64_U  = 0xBA
F64_PROMOTE_F32    = 0xBB
I32_REINTERPRET_F32 = 0xBC
I64_REINTERPRET_F64 = 0xBD
F32_REINTERPRET_I32 = 0xBE
F64_REINTERPRET_I64 = 0xBF

# Sign extension (post-MVP, widely supported)
I32_EXTEND8_S      = 0xC0
I32_EXTEND16_S     = 0xC1
I64_EXTEND8_S      = 0xC2
I64_EXTEND16_S     = 0xC3
I64_EXTEND32_S     = 0xC4

# Prefix opcode for misc instructions
MISC_PREFIX        = 0xFC


# ── Instruction representation ─────────────────────────────────────────────

@dataclass
class MemArg:
    align:  int
    offset: int


@dataclass
class Instr:
    opcode:     int
    imm:        Any = None   # immediate value — type varies by opcode


# ── Decoder ───────────────────────────────────────────────────────────────

def decode_expr(r) -> list[Instr]:
    """
    Decode instructions until the matching END opcode.

    Tracks block nesting depth so nested BLOCK/LOOP/IF bodies are included
    in the flat instruction list rather than stopping at the first END byte.
    """
    depth  = 0
    instrs = []
    while True:
        instr = decode_instr(r)
        instrs.append(instr)
        if instr.opcode in (BLOCK, LOOP, IF):
            depth += 1
        elif instr.opcode == END:
            if depth == 0:
                break
            depth -= 1
    return instrs


def decode_instr(r) -> Instr:
    op = r.read_byte()

    # Control
    if op in (BLOCK, LOOP, IF):
        bt = read_block_type(r)
        return Instr(op, bt)
    if op == ELSE:
        return Instr(op)
    if op == END:
        return Instr(op)
    if op in (BR, BR_IF):
        return Instr(op, r.read_u32())
    if op == BR_TABLE:
        targets = [r.read_u32() for _ in range(r.read_u32())]
        default = r.read_u32()
        return Instr(op, (targets, default))
    if op in (RETURN, UNREACHABLE, NOP):
        return Instr(op)
    if op == CALL:
        return Instr(op, r.read_u32())
    if op == CALL_INDIRECT:
        type_idx  = r.read_u32()
        table_idx = r.read_u32()
        return Instr(op, (type_idx, table_idx))

    # Parametric
    if op == DROP:
        return Instr(op)
    if op == SELECT:
        return Instr(op)
    if op == SELECT_T:
        n = r.read_u32()
        ts = [r.read_byte() for _ in range(n)]
        return Instr(op, ts)

    # Variable
    if op in (LOCAL_GET, LOCAL_SET, LOCAL_TEE, GLOBAL_GET, GLOBAL_SET):
        return Instr(op, r.read_u32())

    # Table
    if op in (TABLE_GET, TABLE_SET):
        return Instr(op, r.read_u32())

    # Memory
    if op in range(I32_LOAD, I64_STORE32 + 1):
        align  = r.read_u32()
        offset = r.read_u32()
        return Instr(op, MemArg(align, offset))
    if op in (MEMORY_SIZE, MEMORY_GROW):
        r.read_byte()  # reserved byte (must be 0)
        return Instr(op)

    # Constants
    if op == I32_CONST:
        return Instr(op, r.read_i32())
    if op == I64_CONST:
        return Instr(op, r.read_i64())
    if op == F32_CONST:
        return Instr(op, r.read_f32())
    if op == F64_CONST:
        return Instr(op, r.read_f64())

    # Reference
    if op == REF_NULL:
        return Instr(op, r.read_byte())
    if op in (REF_IS_NULL, REF_FUNC):
        return Instr(op, r.read_u32() if op == REF_FUNC else None)

    # Misc prefix
    if op == MISC_PREFIX:
        sub = r.read_u32()
        # memory.init, memory.copy, memory.fill, table.init, elem.drop, table.copy, table.grow, table.size, table.fill
        if sub in (8, 9, 10, 11, 12, 13, 14, 15, 16):
            a = r.read_u32()
            b = r.read_u32() if sub in (8, 11, 13) else None
            return Instr(op, (sub, a, b))
        return Instr(op, (sub,))

    # All remaining opcodes have no immediates (numeric ops, conversions, etc.)
    return Instr(op)
