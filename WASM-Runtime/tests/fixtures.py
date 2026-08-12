"""
Minimal hand-assembler for creating test .wasm fixtures without an external compiler.

Each function builds a valid wasm binary from scratch using the binary encoding
specified in the spec. Used exclusively by the test suite.
"""

from __future__ import annotations

import struct


# ── LEB128 helpers ──────────────────────────────────────────────────────────

def uleb128(v: int) -> bytes:
    out = []
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            b |= 0x80
        out.append(b)
        if not v:
            break
    return bytes(out)


def sleb128(v: int) -> bytes:
    out  = []
    more = True
    while more:
        b    = v & 0x7F
        v  >>= 7
        if (v == 0 and (b & 0x40) == 0) or (v == -1 and (b & 0x40) != 0):
            more = False
        else:
            b |= 0x80
        out.append(b)
    return bytes(out)


def vec(items: list[bytes]) -> bytes:
    return uleb128(len(items)) + b"".join(items)


def section(sec_id: int, payload: bytes) -> bytes:
    return bytes([sec_id]) + uleb128(len(payload)) + payload


def module(sections: list[bytes]) -> bytes:
    return b"\x00asm\x01\x00\x00\x00" + b"".join(sections)


def func_type(params: list[int], results: list[int]) -> bytes:
    return (b"\x60"
            + vec([bytes([p]) for p in params])
            + vec([bytes([r]) for r in results]))


def code_body(local_groups: list[tuple[int, int]], body: bytes) -> bytes:
    """local_groups: [(count, valtype), ...]"""
    lgs = vec([uleb128(n) + bytes([t]) for n, t in local_groups])
    inner = lgs + body
    return uleb128(len(inner)) + inner


# ── Specific test module builders ─────────────────────────────────────────

I32 = 0x7F
I64 = 0x7E
F32 = 0x7D
F64 = 0x7C


def make_add_i32() -> bytes:
    """(i32, i32) -> i32  :  a + b"""
    type_sec = section(1, vec([func_type([I32, I32], [I32])]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x03add" + b"\x00" + uleb128(0)]))
    body = b"\x20\x00\x20\x01\x6a\x0b"  # local.get 0, local.get 1, i32.add, end
    code_sec = section(10, vec([code_body([], body)]))
    return module([type_sec, func_sec, export_sec, code_sec])


def make_factorial() -> bytes:
    """i32 -> i32  :  factorial(n)"""
    # func 0: fact(n) = if n<=1 then 1 else n * fact(n-1)
    type_sec = section(1, vec([func_type([I32], [I32])]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x09factorial" + b"\x00" + uleb128(0)]))
    #  local.get 0
    #  i32.const 1
    #  i32.le_s
    #  if (result i32)
    #    i32.const 1
    #  else
    #    local.get 0
    #    local.get 0
    #    i32.const 1
    #    i32.sub
    #    call 0
    #    i32.mul
    #  end
    #  end
    body = (
        b"\x20\x00"          # local.get 0
        b"\x41\x01"          # i32.const 1
        b"\x4c"              # i32.le_s
        b"\x04\x7f"          # if (result i32)
        b"\x41\x01"          #   i32.const 1
        b"\x05"              # else
        b"\x20\x00"          #   local.get 0
        b"\x20\x00"          #   local.get 0
        b"\x41\x01"          #   i32.const 1
        b"\x6b"              #   i32.sub
        b"\x10\x00"          #   call 0
        b"\x6c"              #   i32.mul
        b"\x0b"              # end if
        b"\x0b"              # end func
    )
    code_sec = section(10, vec([code_body([], body)]))
    return module([type_sec, func_sec, export_sec, code_sec])


def make_fibonacci() -> bytes:
    """i32 -> i32  :  iterative fibonacci"""
    type_sec = section(1, vec([func_type([I32], [I32])]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x09fibonacci" + b"\x00" + uleb128(0)]))
    # locals: i=1, a=0, b=1  (3 i32 locals at indices 1,2,3)
    # while i < n: a,b = b, a+b; i++
    # return b if n>0 else 0
    body = (
        b"\x41\x00"          # i32.const 0       ; check n==0
        b"\x20\x00"          # local.get 0 (n)
        b"\x41\x00"          # i32.const 0
        b"\x4e"              # i32.ge_s
        b"\x04\x7f"          # if (result i32)   ; n >= 0
        b"\x20\x00"          # local.get 0
        b"\x41\x00"          # i32.const 0
        b"\x46"              # i32.eq
        b"\x04\x7f"          # if (result i32)   ; n == 0
        b"\x41\x00"          # i32.const 0
        b"\x05"              # else
        b"\x41\x01"          # i32.const 1       ; i = 1
        b"\x21\x01"          # local.set 1
        b"\x41\x00"          # i32.const 0       ; a = 0
        b"\x21\x02"          # local.set 2
        b"\x41\x01"          # i32.const 1       ; b = 1
        b"\x21\x03"          # local.set 3
        b"\x03\x40"          # loop void
        b"\x20\x01"          #   local.get i
        b"\x20\x00"          #   local.get n
        b"\x48"              #   i32.lt_s
        b"\x04\x40"          #   if void
        b"\x20\x02"          #     local.get a
        b"\x20\x02"          #     local.get a
        b"\x20\x03"          #     local.get b
        b"\x6a"              #     i32.add
        b"\x21\x02"          #     local.set a  (a = a+b temporarily wrong)
        b"\x1a"              #     drop (drop old a)
        # fix: a_new = b, b_new = a+b
        # rewrite properly:
    )
    # Simpler iterative fib without above mess:
    # Use straight loop with locals
    body = (
        b"\x20\x00"          # local.get n
        b"\x41\x01"          # i32.const 1
        b"\x4c"              # i32.le_s  (n <= 1)
        b"\x04\x7f"          # if i32
        b"\x20\x00"          #   local.get n  (return n for 0 or 1)
        b"\x05"              # else
        b"\x41\x01"          #   i32.const 1    ; i = 1
        b"\x21\x01"          #   local.set 1
        b"\x41\x00"          #   i32.const 0    ; a = 0
        b"\x21\x02"          #   local.set 2
        b"\x41\x01"          #   i32.const 1    ; b = 1
        b"\x21\x03"          #   local.set 3
        b"\x03\x40"          #   loop void
        b"\x20\x01"          #     local.get i
        b"\x20\x00"          #     local.get n
        b"\x48"              #     i32.lt_s
        b"\x04\x40"          #     if void
        b"\x20\x03"          #       local.get b   ; tmp = b
        b"\x20\x02"          #       local.get a
        b"\x20\x03"          #       local.get b
        b"\x6a"              #       i32.add       ; a+b
        b"\x21\x03"          #       local.set b   ; b = a+b
        b"\x21\x02"          #       local.set a   ; a = old b
        b"\x20\x01"          #       local.get i
        b"\x41\x01"          #       i32.const 1
        b"\x6a"              #       i32.add
        b"\x21\x01"          #       local.set i   ; i++
        b"\x0c\x01"          #       br 1 (continue loop)
        b"\x0b"              #     end if
        b"\x0b"              #   end loop
        b"\x20\x03"          #   local.get b    ; return b
        b"\x0b"              # end if
        b"\x0b"              # end func
    )
    code_sec = section(10, vec([code_body([(3, I32)], body)]))
    return module([type_sec, func_sec, export_sec, code_sec])


def make_memory_ops() -> bytes:
    """Tests memory store/load. Exports: store_load(addr, val) -> val, mem_size() -> i32"""
    # Type 0: (i32,i32)->i32   store_load
    # Type 1: () -> i32         mem_size
    type_sec = section(1, vec([
        func_type([I32, I32], [I32]),
        func_type([], [I32]),
    ]))
    func_sec = section(3, vec([uleb128(0), uleb128(1)]))
    mem_sec  = section(5, vec([b"\x00" + uleb128(1)]))  # 1 page, no max
    export_sec = section(7, vec([
        b"\x0astore_load" + b"\x00" + uleb128(0),
        b"\x08mem_size" + b"\x00" + uleb128(1),
    ]))
    # store_load: i32.store(addr, val); i32.load(addr)
    body0 = (
        b"\x20\x00"    # local.get 0  (addr)
        b"\x20\x01"    # local.get 1  (val)
        b"\x36\x02\x00"  # i32.store align=2 offset=0
        b"\x20\x00"    # local.get 0
        b"\x28\x02\x00"  # i32.load align=2 offset=0
        b"\x0b"
    )
    # mem_size: memory.size
    body1 = b"\x3f\x00\x0b"
    code_sec = section(10, vec([
        code_body([], body0),
        code_body([], body1),
    ]))
    return module([type_sec, func_sec, mem_sec, export_sec, code_sec])


def make_globals() -> bytes:
    """Tests global get/set. Exports: get_g() -> i32, set_g(v: i32)"""
    type_sec = section(1, vec([
        func_type([], [I32]),
        func_type([I32], []),
    ]))
    func_sec   = section(3, vec([uleb128(0), uleb128(1)]))
    global_sec = section(6, vec([
        b"\x7f\x01" + b"\x41\x00\x0b",  # mutable i32, init=0
    ]))
    export_sec = section(7, vec([
        b"\x05get_g" + b"\x00" + uleb128(0),
        b"\x05set_g" + b"\x00" + uleb128(1),
    ]))
    body_get = b"\x23\x00\x0b"           # global.get 0, end
    body_set = b"\x20\x00\x24\x00\x0b"  # local.get 0, global.set 0, end
    code_sec = section(10, vec([
        code_body([], body_get),
        code_body([], body_set),
    ]))
    return module([type_sec, func_sec, global_sec, export_sec, code_sec])


def make_loop_sum() -> bytes:
    """i32 -> i32 : sum(n) = 0+1+2+...+(n-1)"""
    type_sec = section(1, vec([func_type([I32], [I32])]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x08loop_sum" + b"\x00" + uleb128(0)]))
    # local 1 = i, local 2 = acc
    # block void        ← label depth 1 (br 1 exits here)
    #   loop void       ← label depth 0 (br 0 re-enters loop)
    #     i >= n → br_if 1 (exit block)
    #     acc += i; i++
    #     br 0          (continue loop)
    #   end loop
    # end block
    # local.get acc
    body = (
        b"\x41\x00\x21\x01"  # i32.const 0; local.set i
        b"\x41\x00\x21\x02"  # i32.const 0; local.set acc
        b"\x02\x40"          # block void
        b"\x03\x40"          #   loop void
        b"\x20\x01"          #     local.get i
        b"\x20\x00"          #     local.get n
        b"\x4e"              #     i32.ge_s  (i >= n)
        b"\x0d\x01"          #     br_if 1   (exit outer block)
        b"\x20\x02"          #     local.get acc
        b"\x20\x01"          #     local.get i
        b"\x6a"              #     i32.add
        b"\x21\x02"          #     local.set acc
        b"\x20\x01"          #     local.get i
        b"\x41\x01"          #     i32.const 1
        b"\x6a"              #     i32.add
        b"\x21\x01"          #     local.set i
        b"\x0c\x00"          #     br 0  (re-enter loop)
        b"\x0b"              #   end loop
        b"\x0b"              # end block
        b"\x20\x02"          # local.get acc
        b"\x0b"              # end func
    )
    code_sec = section(10, vec([code_body([(2, I32)], body)]))
    return module([type_sec, func_sec, export_sec, code_sec])


def make_f64_arith() -> bytes:
    """(f64, f64) -> f64 : multiply"""
    type_sec = section(1, vec([func_type([F64, F64], [F64])]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x06f64mul" + b"\x00" + uleb128(0)]))
    body = b"\x20\x00\x20\x01\xa2\x0b"  # local.get 0, local.get 1, f64.mul, end
    code_sec = section(10, vec([code_body([], body)]))
    return module([type_sec, func_sec, export_sec, code_sec])


def make_import_func() -> bytes:
    """Imports env.log(i32); calls it from exported run(i32)."""
    type_sec = section(1, vec([
        func_type([I32], []),   # type 0: (i32) -> ()
        func_type([I32], []),   # type 1: same (for export)
    ]))
    import_sec = section(2, vec([
        b"\x03env\x03log\x00" + uleb128(0),  # import env.log as func type 0
    ]))
    func_sec = section(3, vec([uleb128(0)]))
    export_sec = section(7,
        vec([b"\x03run" + b"\x00" + uleb128(1)]))
    # run(x): env.log(x)
    body = b"\x20\x00\x10\x00\x0b"  # local.get 0, call 0 (imported log), end
    code_sec = section(10, vec([code_body([], body)]))
    return module([type_sec, import_sec, func_sec, export_sec, code_sec])
