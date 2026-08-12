# WebAssembly Runtime

A pure-Python WebAssembly interpreter that parses the `.wasm` binary format, decodes every instruction and executes the complete MVP instruction set on a stack machine. No external dependencies beyond the standard library. Real `.wasm` binaries compiled from C or Rust run on it unchanged.

## The Hard Parts

**Binary format parsing from scratch.** The `.wasm` format uses unsigned LEB128 for almost every integer — type indices, function indices, local counts, memory offsets, even block type encodings. Signed LEB128 is used for constant operands. The parser reads every section in one linear pass using a cursor-based `BinaryReader` and returns a structured `WasmModule` object with no retained raw bytes.

**Nested control flow as a flat instruction list.** The wasm spec encodes control flow with balanced `block`/`loop`/`if`/`end` opcodes in a flat byte stream. Most real implementations use a label stack during decoding; this runtime decodes the entire function body into a flat `list[Instr]` and resolves nesting at execution time using `_collect_block` and `_collect_if`, which scan forward counting depth to find matching `end` opcodes. This keeps decoding simple at the cost of O(n) forward scans — acceptable for an interpreter.

**Loop re-entry via `br 0`.** In wasm, `br 0` inside a `loop` means "jump back to the loop header" (re-execute from the top), not "exit the loop". `br 0` inside a `block` means "exit the block". The executor distinguishes these by checking the enclosing frame kind: loops raise `_Break(0)` which the loop handler catches and re-enters; blocks propagate `_Break(0)` upward by re-raising with depth decremented.

**Integer semantics.** Python integers are unbounded, but wasm i32/i64 arithmetic wraps at 32/64 bits and has distinct signed/unsigned variants. Every arithmetic result is masked through `_i32` / `_u32` / `_i64` / `_u64` helpers. Division uses Python's floor division with sign-corrected truncation. Shifts mask the shift amount to the register width (31 bits for i32, 63 bits for i64) per the spec.

**f32 precision.** Python floats are IEEE 754 double precision. wasm `f32` operations must produce single-precision results, so every f32 output is rounded through `struct.pack("<f", v)` → `struct.unpack("<f", ...)`. Without this, `f32.add` would silently produce double-precision results that differ from the spec.

## Usage

```python
from wasm.runtime import load_file, load_bytes

# From a compiled wasm binary
inst = load_file("program.wasm")
result = inst.call("add", 3, 4)    # [7]

# With imports (host functions exposed to the wasm module)
inst = load_bytes(wasm_bytes, imports={
    "env": {
        "print_i32": lambda v: print(v),
        "memory":    memory_object,
    }
})

# Inspect exports
print(inst.exports())              # {"add": "func", "memory": "mem", ...}

# Access memory directly
mem = inst.get_export("memory")    # returns Memory object
mem.write_bytes(0, b"hello")
print(mem.read_bytes(0, 5))        # b"hello"

# Access globals
value = inst.globals_[0]
```

## Supported Instructions

All MVP instructions are implemented including:

- Control: `block`, `loop`, `if`/`else`, `br`, `br_if`, `br_table`, `return`, `call`, `call_indirect`, `unreachable`
- Parametric: `drop`, `select`
- Variable: `local.get/set/tee`, `global.get/set`
- Memory: all 14 load variants (i32/i64/f32/f64, 8/16/32-bit with sign extension), all 9 store variants, `memory.size`, `memory.grow`
- Constants: `i32.const`, `i64.const`, `f32.const`, `f64.const`
- Integer arithmetic: all i32 and i64 add/sub/mul/div/rem/and/or/xor/shl/shr/rotl/rotr, clz/ctz/popcnt
- Float arithmetic: all f32 and f64 abs/neg/ceil/floor/trunc/nearest/sqrt/add/sub/mul/div/min/max/copysign
- Comparisons: all i32/i64 signed and unsigned comparisons, all f32/f64 comparisons
- Conversions: all 18 numeric conversion instructions
- Sign extension: i32.extend8_s/extend16_s, i64.extend8_s/extend16_s/extend32_s
- Reinterpret: all 4 reinterpret instructions

## Running Tests

```bash
pytest tests/ -v
```

The test suite requires no external tools. All `.wasm` fixtures are generated in Python by `tests/fixtures.py`, which hand-assembles valid wasm binaries from scratch using the binary encoding — no C compiler or `wat2wasm` needed.

## Running a Real .wasm Binary

Any `.wasm` binary compiled with `clang --target=wasm32-unknown-unknown -nostdlib` or `rustc --target wasm32-unknown-unknown` works, provided it doesn't use WASI syscalls beyond what you supply as imports.

```bash
# Compile a C function to wasm (requires clang)
clang --target=wasm32-unknown-unknown -nostdlib -Wl,--export-all -o add.wasm add.c

# Run it
python -c "
from wasm.runtime import load_file
inst = load_file('add.wasm')
print(inst.call('add', 10, 20))
"
```

## File Map

| Path | Description |
|------|-------------|
| `wasm/binary.py` | LEB128 (signed and unsigned), UTF-8, raw read cursor |
| `wasm/types.py` | ValType, FuncType, Limits, BlockType, reader helpers |
| `wasm/instructions/decode.py` | All opcode constants, `decode_instr`, `decode_expr` |
| `wasm/parser.py` | Full module parser — all 12 sections, `WasmModule` dataclass |
| `wasm/memory.py` | 64 KiB-page linear memory with all load/store variants |
| `wasm/executor.py` | Stack machine — all MVP instructions, block/loop/if/br/br_table |
| `wasm/instance.py` | Module instantiation, import resolution, data/element init |
| `wasm/runtime.py` | Public API — `load_bytes`, `load_file` |
| `tests/fixtures.py` | Hand-assembles test `.wasm` binaries in pure Python |
| `tests/test_runtime.py` | 67 tests covering parser, memory and execution |
