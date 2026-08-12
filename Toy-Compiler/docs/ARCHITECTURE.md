# Architecture — Zap Compiler

## Overview

Zap is a statically typed toy language compiled to bytecode for a stack-based
virtual machine. The compiler is implemented twice — once in Python and once in
Rust — using identical algorithms, identical bytecode semantics and the same
test suite, allowing a direct comparison of language-specific tradeoffs. See
the README for the comparison table.

---

## Pipeline

```
Source text
    │
    ▼
┌─────────┐    tokens
│  Lexer  │──────────────►┐
└─────────┘               │
                          ▼
                    ┌──────────┐    AST
                    │  Parser  │──────────────►┐
                    └──────────┘               │
                                               ▼
                                       ┌──────────────┐
                                       │ Type Checker │  (static types)
                                       └──────┬───────┘
                                              │ typed AST
                                              ▼
                                       ┌──────────────┐
                                       │   Code Gen   │  (AST → bytecode)
                                       └──────┬───────┘
                                              │ CompiledProgram
                                              ▼
                                       ┌──────────────┐
                                       │  Stack VM    │  (interpreter)
                                       └──────────────┘
```

---

## Language — Zap

### Type system

Three primitive types: `int` (64-bit signed), `bool` and `void`.
All variables are statically typed, declared at definition with `: type`,
and cannot be redeclared. Type mismatches are caught before execution.

### Grammar (simplified BNF)

```
program   = (fn_decl | stmt)*
fn_decl   = 'fn' IDENT '(' params? ')' '->' type block
params    = param (',' param)*
param     = IDENT ':' type
block     = '{' stmt* '}'

stmt      = 'let' IDENT ':' type '=' expr ';'
          | 'return' expr? ';'
          | 'if' expr block ('else' block)?
          | 'while' expr block
          | 'print' '(' expr ')' ';'
          | expr ';'

expr      = assign | or | and | eq | cmp | add | mul | unary | call | primary
assign    = IDENT '=' assign
primary   = INT | 'true' | 'false' | IDENT | '(' expr ')'

type      = 'int' | 'bool' | 'void'
```

### Operator precedence (low → high)

| Level | Operators           |
|-------|---------------------|
| 1     | `=`  (right assoc)  |
| 2     | `\|\|`              |
| 3     | `&&`                |
| 4     | `==`  `!=`          |
| 5     | `<` `>` `<=` `>=`  |
| 6     | `+` `-`             |
| 7     | `*` `/`             |
| 8     | `!` unary `-`       |

---

## Lexer

Single-pass character scanner with one character of lookahead for two-character
tokens (`==`, `!=`, `<=`, `>=`, `&&`, `||`, `->`). Produces a flat token list
with line numbers attached. Line comments (`//`) are consumed and discarded.

No token stream is shared across passes — each compilation is fully pipeline.

---

## Parser

Recursive descent, top-down. One function per grammar rule. Operator precedence
is encoded structurally: each precedence level is a separate function that calls
the level above it, so the call stack itself represents the parse tree.

The assignment rule peeks two tokens ahead (identifier followed by `=`) to
distinguish assignment from a plain identifier expression before committing.

---

## Type Checker

Two-pass design:

**Pass 1** — collect function signatures. This allows forward references: a
function can call another defined later in the same file.

**Pass 2** — walk every statement and expression, maintaining a linked-list
scope chain. Each scope lookup walks parent pointers until the variable is
found or the chain is exhausted.

All type errors are reported with source line numbers. The checker does not
attempt recovery — it stops at the first error.

---

## Code Generator

Single-pass AST walk that emits a flat list of `Instr` values per function.
Each `Instr` has an opcode, an integer payload and a string payload; most
instructions use only one.

**Jump patching.** Forward jumps (`if`, `while` exits) are emitted with a
placeholder offset of 0, and the actual offset is back-patched once the target
address is known. Back-edges (while loop body to condition) are computed
directly since the target is already emitted.

Jump offsets are relative to the instruction after the jump:

```
ip += offset   (signed; negative = backwards)
```

This keeps the VM implementation trivially simple — no address tables needed.

### Instruction set (25 opcodes)

| Opcode       | Stack effect           | Description                    |
|--------------|------------------------|--------------------------------|
| PUSH_INT n   | → int                  | Push integer literal           |
| PUSH_BOOL b  | → bool                 | Push boolean literal           |
| LOAD name    | → value                | Load local variable            |
| STORE name   | value →                | Store local variable           |
| ADD/SUB/MUL/DIV | int int → int       | Arithmetic                     |
| NEG          | int → int              | Unary negation                 |
| EQ/NEQ       | a b → bool             | Equality (any type)            |
| LT/GT/LEQ/GEQ | int int → bool        | Comparison                     |
| AND/OR       | bool bool → bool       | Logical                        |
| NOT          | bool → bool            | Logical not                    |
| JMP n        | —                      | Unconditional jump             |
| JMP_FALSE n  | bool →                 | Jump if false                  |
| CALL fn k    | arg×k → retval         | Call function with k args      |
| RET          | retval →               | Return from function           |
| PRINT        | value →                | Print and pop                  |
| POP          | value →                | Discard top                    |
| HALT         | —                      | Stop execution                 |

---

## Stack VM

Each active call is a `Frame` containing:

- A reference to the function's `FnChunk` (code and parameter names)
- An instruction pointer `ip`
- A `locals` map (variable name → value)
- A value stack

Frames are maintained in a `Vec` acting as a call stack. `CALL` pushes a new
frame, binds arguments to parameter names in `locals`, and resumes. `RET` pops
the frame and pushes the return value to the caller's stack.

The main execution loop is a single `loop` with a `match` on the current
instruction's opcode. No indirect dispatch tables — Rust's and Python's match
statements compile this efficiently.

---

## Python vs Rust implementation notes

See the README comparison table for measurements. The key structural
differences are:

**Ownership.** The Python type checker uses a singly-linked Scope chain via
`parent` references that are shared freely. In Rust, ownership rules require
consuming the old scope to build a new one and consuming the child scope to
recover the parent. The `enter()` / `leave()` pattern using `std::mem::replace`
achieves this without unsafe code.

**Error handling.** Python raises exceptions that propagate implicitly. Rust
uses `Result<T, String>` everywhere, making every fallible call explicit with
`?`. This is more verbose but makes the error surface visible in the type
signature.

**Pattern matching.** Both implementations use structural pattern matching for
the VM dispatch loop. Python's `match` (3.10+) is syntactically identical to
Rust's for this use case.

**Pickling / serialisation.** Python bytecode is not serialised in this
implementation; the Rust `CompiledProgram` is likewise an in-memory struct.
Persistence is out of scope for both.

---

## Files

```
python/
  zap/
    ast_nodes.py        — dataclass AST nodes
    lexer.py            — tokenizer
    parser.py           — recursive descent parser
    type_checker.py     — two-pass static type checker
    codegen.py          — AST → bytecode
    vm.py               — stack VM
    __init__.py         — public API + compile_and_run()
  scripts/zapc.py       — CLI: run or disassemble .zap files
  tests/test_compiler.py
  pyproject.toml

rust/
  src/
    ast.rs              — AST node types
    lexer.rs            — tokenizer
    parser.rs           — recursive descent parser
    type_checker.rs     — two-pass static type checker
    codegen.rs          — AST → bytecode
    vm.rs               — stack VM
    lib.rs              — crate root + compile_and_run()
    main.rs             — CLI: run or disassemble .zap files
  tests/integration.rs
  Cargo.toml

examples/
  fibonacci.zap
  fizzbuzz.zap
  factorial.zap

docs/
  ARCHITECTURE.md       — this file
```
