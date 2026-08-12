import math
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from wasm.binary import BinaryReader
from wasm.runtime import load_bytes
from wasm.memory import Memory
from wasm.parser import parse
from wasm.types import ValType
from tests.fixtures import (
    make_add_i32, make_factorial, make_fibonacci, make_memory_ops,
    make_globals, make_loop_sum, make_f64_arith, make_import_func,
    uleb128, sleb128,
)


# ── BinaryReader ─────────────────────────────────────────────────────────────

class TestBinaryReader:
    def test_read_byte(self):
        r = BinaryReader(b"\x42")
        assert r.read_byte() == 0x42

    def test_eof(self):
        r = BinaryReader(b"\x01")
        r.read_byte()
        assert r.eof()

    def test_uleb128_single_byte(self):
        r = BinaryReader(uleb128(64))
        assert r.read_u32() == 64

    def test_uleb128_multibyte(self):
        r = BinaryReader(uleb128(300))
        assert r.read_u32() == 300

    def test_uleb128_large(self):
        r = BinaryReader(uleb128(624485))
        assert r.read_u32() == 624485

    def test_sleb128_positive(self):
        r = BinaryReader(sleb128(42))
        assert r.read_i32() == 42

    def test_sleb128_negative(self):
        r = BinaryReader(sleb128(-1))
        assert r.read_i32() == -1

    def test_sleb128_minus_128(self):
        r = BinaryReader(sleb128(-128))
        assert r.read_i32() == -128

    def test_f32(self):
        v = 3.14
        r = BinaryReader(struct.pack("<f", v))
        assert abs(r.read_f32() - v) < 1e-5

    def test_f64(self):
        v = 2.718281828
        r = BinaryReader(struct.pack("<d", v))
        assert abs(r.read_f64() - v) < 1e-10

    def test_read_name(self):
        name = "hello"
        data = uleb128(len(name)) + name.encode()
        r = BinaryReader(data)
        assert r.read_name() == "hello"

    def test_slice(self):
        r = BinaryReader(b"\x01\x02\x03\x04")
        assert r.slice(2) == b"\x01\x02"
        assert r.pos == 2

    def test_sub_reader(self):
        r = BinaryReader(b"\x01\x02\x03\x04")
        sub = r.sub_reader(2)
        assert sub.read_byte() == 0x01
        assert r.pos == 2

    def test_eof_raises(self):
        r = BinaryReader(b"")
        with pytest.raises(EOFError):
            r.read_byte()


# ── Module parsing ────────────────────────────────────────────────────────────

class TestParsing:
    def test_parse_add_i32(self):
        mod = parse(make_add_i32())
        assert len(mod.types) == 1
        assert len(mod.func_types) == 1
        assert len(mod.codes) == 1
        assert any(e.name == "add" for e in mod.exports)

    def test_parse_factorial(self):
        mod = parse(make_factorial())
        assert mod.func_type(0).params == (ValType.I32,)
        assert mod.func_type(0).results == (ValType.I32,)

    def test_parse_memory_ops(self):
        mod = parse(make_memory_ops())
        assert len(mod.mems) == 1
        assert mod.mems[0].limits.min == 1

    def test_parse_globals(self):
        mod = parse(make_globals())
        assert len(mod.globals_) == 1
        assert mod.globals_[0].global_type.mutable is True
        assert mod.globals_[0].global_type.val_type == ValType.I32

    def test_parse_imports(self):
        mod = parse(make_import_func())
        assert len(mod.imports) == 1
        assert mod.imports[0].module == "env"
        assert mod.imports[0].name == "log"
        assert mod.imports[0].desc.kind == "func"

    def test_invalid_magic_raises(self):
        with pytest.raises(ValueError, match="Not a wasm binary"):
            parse(b"\x00bad\x01\x00\x00\x00")

    def test_invalid_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            parse(b"\x00asm\x02\x00\x00\x00")


# ── Memory ────────────────────────────────────────────────────────────────────

class TestMemory:
    def test_initial_size(self):
        m = Memory(1)
        assert m.size == 1
        assert m.byte_size == 65536

    def test_grow_returns_prev_size(self):
        m = Memory(1)
        prev = m.grow(2)
        assert prev == 1
        assert m.size == 3

    def test_grow_beyond_max_returns_neg1(self):
        m = Memory(1, max_pages=2)
        assert m.grow(5) == -1
        assert m.size == 1

    def test_store_load_i32(self):
        m = Memory(1)
        m.store_i32(0, 0xDEADBEEF)
        assert m.load_i32(0) == -559038737   # signed interpretation

    def test_store_load_i64(self):
        m = Memory(1)
        m.store_i64(0, 123456789012345)
        assert m.load_i64(0) == 123456789012345

    def test_store_load_f64(self):
        m = Memory(1)
        m.store_f64(8, 3.14159)
        assert abs(m.load_f64(8) - 3.14159) < 1e-10

    def test_load8_sign_extension(self):
        m = Memory(1)
        m.store_i8(0, 0xFF)
        assert m.load_i8_s(0) == -1
        assert m.load_i8_u(0) == 255

    def test_load16_sign_extension(self):
        m = Memory(1)
        m.store_i16(0, 0x8000)
        assert m.load_i16_s(0) == -32768
        assert m.load_i16_u(0) == 32768

    def test_out_of_bounds_raises(self):
        m = Memory(1)
        with pytest.raises(Exception):
            m.load_i32(65536)

    def test_write_read_bytes(self):
        m = Memory(1)
        m.write_bytes(100, b"hello")
        assert m.read_bytes(100, 5) == b"hello"

    def test_fill(self):
        m = Memory(1)
        m.fill(0, 0xAB, 4)
        assert m.read_bytes(0, 4) == b"\xab\xab\xab\xab"

    def test_copy(self):
        m = Memory(1)
        m.write_bytes(0, b"abcdef")
        m.copy(10, 0, 6)
        assert m.read_bytes(10, 6) == b"abcdef"

    def test_offset_addressing(self):
        m = Memory(1)
        m.store_i32(0, 42, offset=4)
        assert m.load_i32(0, offset=4) == 42


# ── Execution — i32 arithmetic ───────────────────────────────────────────────

class TestI32Arithmetic:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_add_i32())

    def test_add(self, inst):
        assert inst.call("add", 3, 4) == [7]

    def test_add_negative(self, inst):
        assert inst.call("add", -1, -1) == [-2]

    def test_add_overflow_wraps(self, inst):
        result = inst.call("add", 0x7FFFFFFF, 1)
        assert result == [-0x80000000]

    def test_add_zero(self, inst):
        assert inst.call("add", 0, 0) == [0]


class TestFactorial:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_factorial())

    def test_fact_0(self, inst):
        assert inst.call("factorial", 0) == [1]

    def test_fact_1(self, inst):
        assert inst.call("factorial", 1) == [1]

    def test_fact_5(self, inst):
        assert inst.call("factorial", 5) == [120]

    def test_fact_10(self, inst):
        assert inst.call("factorial", 10) == [3628800]


class TestFibonacci:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_fibonacci())

    def test_fib_0(self, inst):
        assert inst.call("fibonacci", 0) == [0]

    def test_fib_1(self, inst):
        assert inst.call("fibonacci", 1) == [1]

    def test_fib_2(self, inst):
        assert inst.call("fibonacci", 2) == [1]

    def test_fib_7(self, inst):
        assert inst.call("fibonacci", 7) == [13]

    def test_fib_10(self, inst):
        assert inst.call("fibonacci", 10) == [55]


class TestLoopSum:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_loop_sum())

    def test_sum_0(self, inst):
        assert inst.call("loop_sum", 0) == [0]

    def test_sum_5(self, inst):
        assert inst.call("loop_sum", 5) == [0+1+2+3+4]

    def test_sum_100(self, inst):
        n = 100
        assert inst.call("loop_sum", n) == [n*(n-1)//2]


# ── Execution — memory ────────────────────────────────────────────────────────

class TestMemoryExecution:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_memory_ops())

    def test_store_and_load(self, inst):
        assert inst.call("store_load", 0, 42) == [42]

    def test_store_and_load_offset(self, inst):
        assert inst.call("store_load", 64, 999) == [999]

    def test_mem_size_initial(self, inst):
        assert inst.call("mem_size") == [1]


# ── Execution — globals ───────────────────────────────────────────────────────

class TestGlobals:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_globals())

    def test_initial_value(self, inst):
        assert inst.call("get_g") == [0]

    def test_set_and_get(self, inst):
        inst.call("set_g", 77)
        assert inst.call("get_g") == [77]

    def test_set_multiple(self, inst):
        inst.call("set_g", 100)
        inst.call("set_g", 200)
        assert inst.call("get_g") == [200]


# ── Execution — f64 ──────────────────────────────────────────────────────────

class TestF64:
    @pytest.fixture(scope="class")
    def inst(self):
        return load_bytes(make_f64_arith())

    def test_multiply(self, inst):
        r = inst.call("f64mul", 2.0, 3.0)
        assert abs(r[0] - 6.0) < 1e-10

    def test_multiply_pi(self, inst):
        r = inst.call("f64mul", math.pi, 2.0)
        assert abs(r[0] - 2 * math.pi) < 1e-10

    def test_multiply_negative(self, inst):
        r = inst.call("f64mul", -1.5, 4.0)
        assert abs(r[0] - (-6.0)) < 1e-10


# ── Imports ───────────────────────────────────────────────────────────────────

class TestImports:
    def test_imported_function_called(self):
        log_calls = []
        inst = load_bytes(make_import_func(), imports={
            "env": {"log": lambda x: log_calls.append(x)},
        })
        inst.call("run", 42)
        assert log_calls == [42]

    def test_imported_function_called_multiple(self):
        log_calls = []
        inst = load_bytes(make_import_func(), imports={
            "env": {"log": lambda x: log_calls.append(x)},
        })
        inst.call("run", 1)
        inst.call("run", 2)
        inst.call("run", 3)
        assert log_calls == [1, 2, 3]

    def test_missing_import_raises_on_call(self):
        inst = load_bytes(make_import_func())
        with pytest.raises(Exception):
            inst.call("run", 0)


# ── Instance API ──────────────────────────────────────────────────────────────

class TestInstanceAPI:
    def test_exports_dict(self):
        inst = load_bytes(make_add_i32())
        assert "add" in inst.exports()
        assert inst.exports()["add"] == "func"

    def test_get_export_func(self):
        inst = load_bytes(make_add_i32())
        idx = inst.get_export("add")
        assert isinstance(idx, int)

    def test_get_export_missing_raises(self):
        inst = load_bytes(make_add_i32())
        with pytest.raises(KeyError):
            inst.get_export("nonexistent")

    def test_get_export_mem(self):
        inst = load_bytes(make_memory_ops())
        mem = inst.get_export("memory") if "memory" in inst.exports() else inst.mem
        assert mem is not None

    def test_get_export_global(self):
        inst = load_bytes(make_globals())
        inst.call("set_g", 55)
        # globals_ index 0
        assert inst.globals_[0] == 55
