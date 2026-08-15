# WebAssembly Runtime — Architecture

## Pipeline

```
.wasm bytes
    │
    ▼
BinaryReader          wasm/binary.py
  LEB128, slices, sub-readers
    │
    ▼
Module Parser         wasm/parser.py
  Section dispatch → WasmModule dataclass
    │
    ▼
Module Instantiation  wasm/instance.py
  Allocate Memory / Tables / Globals
  Resolve Imports
  Apply Data / Element segments
  Run start function
    │
    ▼
Executor              wasm/executor.py
  Stack machine — Executor.call() → _exec() loop
    │
    ▼
Result list
```

## Binary Reader — `wasm/binary.py`

`BinaryReader` wraps a `bytes` object with a mutable position cursor. Key methods:

- `read_u32()` / `read_i32()` — unsigned and signed LEB128. LEB128 uses 7 bits per byte with the MSB as a continuation flag. A 32-bit value requires at most 5 bytes (ceil(32/7)). The signed variant sign-extends based on the MSB of the final byte.
- `sub_reader(length)` — extracts a sub-buffer of exactly `length` bytes and returns a fresh `BinaryReader`. Used for section parsing: each section is read as a sub-buffer so the outer reader advances past it regardless of whether the section parser consumes all bytes.
- `read_vec(fn)` — reads a u32 count then calls `fn(self)` that many times; the standard wasm vector encoding.

## Module Parser — `wasm/parser.py`

The top-level `parse(data)` function reads the 8-byte preamble (magic + version), then dispatches on section IDs in a `while not r.eof()` loop. Each section is read into a sub-reader and handled by a dedicated `_parse_*_section` function.

**Section ID map:**

| ID | Name | Contents |
|----|------|----------|
| 0 | Custom | Name + raw bytes (stored verbatim) |
| 1 | Type | `vec(functype)` — all function signatures |
| 2 | Import | module, name, kind, descriptor for each import |
| 3 | Function | `vec(typeidx)` — one entry per local function |
| 4 | Table | `vec(tabletype)` |
| 5 | Memory | `vec(memtype)` — limits (min, optional max) in pages |
| 6 | Global | `vec(globaldef)` — type + mutable flag + init const expr |
| 7 | Export | name, kind (func/table/mem/global), index |
| 8 | Start | single `funcidx` |
| 9 | Element | table initialisation — multiple encoding variants |
| 10 | Code | `vec(funcbody)` — locals + flat instruction list |
| 11 | Data | memory initialisation bytes + offset const expr |
| 12 | DataCount | count of data segments (bulk memory extension) |

**Function type resolution.** `WasmModule.func_type(idx)` accepts a flat function index spanning both imports and local functions. If `idx < n_imported_funcs`, the type comes from the import's type index. Otherwise, `func_types[idx - n_imported_funcs]` is the type section index for the local function.

**Instruction decoding.** Code section parsing calls `decode_expr(r)` for each function body. `decode_expr` calls `decode_instr` in a loop and tracks nesting depth: `block`/`loop`/`if` increment depth; `end` decrements it and stops only when depth reaches zero. This produces a single flat `list[Instr]` per function — no nested lists, no tree structure — which simplifies the executor.

Instruction immediates are decoded inline: memory instructions decode `align` and `offset` into a `MemArg`; control instructions decode their label indices; const instructions decode their literal values via the appropriate LEB128 or `struct` read.

## Memory — `wasm/memory.py`

`Memory` backs a `bytearray` grown in 64 KiB pages. The `grow(delta)` method returns the previous page count on success or -1 on failure, matching the wasm `memory.grow` semantics exactly.

All load operations use `struct.unpack_from` for multi-byte reads to handle alignment-agnostic little-endian decoding. The `_check(addr, size)` method validates that `addr + size <= byte_size` and raises `MemoryError` on out-of-bounds access.

Sign extension for sub-word loads:
- `load_i8_s` / `load_i16_s` / `load_i32_s` return Python ints with negative values represented directly (Python two's-complement semantics match here).
- `load_i8_u` / `load_i16_u` / `load_i32_u` return unsigned values (always non-negative).

## Executor — `wasm/executor.py`

`Executor._exec(instrs, stack, local_vals)` iterates over a flat `list[Instr]` using an explicit integer index `i`. This is a `while` loop rather than `for` to allow `i` to jump forward by more than 1 when a `block`/`loop`/`if` is encountered (the body must be skipped after execution).

**Control flow model.** Three Python exceptions serve as jump signals:

- `_Return(values)` — raised by `return`, caught by `Executor.call` to extract the return values from the exception payload rather than the stack.
- `_Break(depth)` — raised by `br`, `br_if` and `br_table`. Each structured control instruction (`block`, `loop`, `if`) catches `_Break` and decrements `depth`; when `depth` reaches 0 the break resolves at that level.

**Block execution (depth 0 = exit block):**
```
try:
    _exec(body)
except _Break as br:
    if br.depth > 0: raise _Break(br.depth - 1)
    # br.depth == 0: stay here (exit block)
```

**Loop execution (depth 0 = re-enter loop):**
```
while True:
    try:
        _exec(body)
        break
    except _Break as br:
        if br.depth == 0: continue   # re-enter
        raise _Break(br.depth - 1)
```

**Nested blocks.** `_collect_block(instrs, start)` scans forward from `start` tracking nesting depth to find the matching `end` opcode. This is O(n) per block entry. `_collect_if(instrs, start)` does the same but also partitions the body at the first depth-0 `else` opcode.

**Integer masking.** Wasm integers are modular. Python's arbitrary-precision integers require explicit masking after every operation:
- `_i32(v)` = `(v & 0xFFFFFFFF)` with sign extension to signed 32-bit range
- `_u32(v)` = `v & 0xFFFFFFFF` (always non-negative)
- Same pattern for 64-bit

Division uses Python `int / int` with `math.trunc` to implement truncation-toward-zero semantics (Python's `//` floors instead).

**f32 rounding.** `_f32(v)` round-trips through `struct.pack("<f")` to truncate to 32-bit precision. This is called on every f32 arithmetic output.

**`call_indirect`.** Pops an element index, bounds-checks the table, retrieves the function index stored there, and validates that the target function's type matches the static type index in the instruction. This is the wasm dynamic call mechanism — equivalent to a C function pointer call through a function table.

## Module Instance — `wasm/instance.py`

`ModuleInstance.__init__` performs instantiation in spec order:

1. Import resolution — for each import, look up `imports[module][name]`. Python callables become `HostFunc` wrappers; `Memory` and `list` objects are used directly for memory and table imports. Missing imports produce stub functions that raise at call time.

2. Local allocation — `Memory(min, max)` for each memory definition; `[None] * min` for each table; `_eval_const_expr(init_expr)` for each global.

3. Data segment initialisation — active segments write their bytes directly into memory at the const-expression offset.

4. Element segment initialisation — active segments write function indices into the table at the const-expression offset.

5. Start function — called with no arguments if a start index is present.

**`_eval_const_expr`** handles the restricted expression language used in section initialisers: `i32.const`, `i64.const`, `f32.const`, `f64.const` and `global.get` of a previously defined (or imported) global.

## Test Fixture Assembler — `tests/fixtures.py`

The test suite creates valid `.wasm` binaries entirely in Python without any external toolchain. `tests/fixtures.py` provides:

- `uleb128(v)` / `sleb128(v)` — LEB128 byte encoders
- `section(id, payload)` — wraps payload with section ID and length prefix
- `vec(items)` — prepends count to a concatenated list of byte strings
- `func_type(params, results)` / `code_body(locals, body)` — build specific section entries
- Eight complete module builders: `make_add_i32`, `make_factorial`, `make_fibonacci`, `make_memory_ops`, `make_globals`, `make_loop_sum`, `make_f64_arith`, `make_import_func`

Each builder constructs the minimum set of sections required for the function being tested. The bytecode bodies are hand-written in hex matching the wasm binary encoding exactly.

## Design Decisions

**Flat instruction list vs tree.** A tree representation (each block as a nested list of children) would eliminate `_collect_block` scans but complicates the decoder. The flat list makes decoding simpler and keeps `decode_expr` to ~15 lines. The runtime cost of forward scanning is negligible for the test programs.

**Python exceptions for control flow.** Using `raise _Break(depth)` mimics how real runtimes unwind the label stack. The alternative — passing a "break signal" as a return value from `_exec` — would require every instruction to check the return value, adding noise to the hot path. Python exceptions have non-trivial overhead, but they make the control flow logic very readable.

**No validation pass.** A production runtime validates the module (type-checks every instruction, verifies stack discipline) before execution. This implementation skips validation to keep the codebase focused on the parsing and execution mechanics. Type errors manifest as Python exceptions at runtime.
