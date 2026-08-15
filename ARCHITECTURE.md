# Architecture

Seven modules; four of them form a pipeline. Each module's own design is in
[`docs/`](docs). This is about the joins.

```
   toolchain/cli.py           lang build | run | modules
          │
   toolchain/pipeline.py      the only file that knows all four stages exist
          │
   ┌──────┴──────┬─────────────┬──────────────┐
compiler    wasm-runtime    profiler      (registry)
 .zap→.wasm   executes      measures      what is here
```

## The WebAssembly backend

It emits from the **AST**, not from the VM bytecode. That is the load-bearing
decision.

Zap's bytecode is flat with signed jump offsets. WebAssembly has no arbitrary
jumps — only `block`, `loop`, `if` and branches to enclosing labels. Going from
offsets to structure is control-flow-graph reconstruction; going from the AST is
a direct mapping, because `IfStmt` and `WhileStmt` *are* the structure:

```
if cond { A } else { B }   →   cond; if; A; else; B; end
while cond { B }           →   block; loop; cond; i32.eqz; br_if 1; B; br 0; end; end
```

The `while` shape is worth reading twice. WebAssembly branches only outwards, so
leaving a loop needs a label that is already open — hence the outer `block`,
whose `end` is where `br_if 1` lands.

Other decisions:

- **`int` and `bool` are both `i32`**, with `bool` normalised to 0/1, because
  WebAssembly's comparison instructions produce exactly that and its `if` tests
  non-zero.
- **`print` is an import**, `env.print(i32) -> ()`. A module has no way to reach
  the outside; the host supplies it, and here the host is the pipeline.
- **A non-`void` function with no trailing `return` emits `unreachable`** rather
  than a zero. The validator needs the stack to be right on every path; inventing
  a return value would hide a compiler bug behind a plausible number.
- **Assignment uses `local.tee`**, which stores and leaves the value, so
  assignment stays an expression exactly as it is in Zap.

## Why the stack VM stayed

It is the reference implementation. `--compare` compiles a program both ways,
runs both, and asserts the outputs match; every example in the repository is
checked that way in the test suite.

A second backend with nothing to check it against is a second set of bugs.

## What the pipeline found

**A runtime bug.** The `if` handler advanced the instruction pointer to `skip +
1`, which lands *on* the matching `END` — and `END` in the dispatch loop is
`break`. Every instruction after an `if` was discarded, so a function returned
whatever was on the stack before the branch. `BLOCK` and `LOOP` already skipped
body-plus-`END`; `IF` now does the same.

It survived because the runtime's fixtures were hand-written modules that never
had code after an `if`. A compiler emitting real control flow hit it on the
first recursive function. That is the argument for the merge in one incident:
the modules test each other in ways their own fixtures do not.

**A performance finding, recorded and not acted on.** `_collect_if` re-scans
block boundaries on every execution rather than caching them — about 5% of
runtime on a branch-heavy program. Caching it is a change to the interpreter's
hot path and deserves its own benchmark, so it is written down rather than
quietly changed.

## Profiling the right thing

`lang run --profile` samples the *interpreter* while it runs the program. The
frames that come back are `executor.py`, not the Zap source, and the CLI says so
in as many words — because a profile that looks like it is about your program
and is actually about the runtime is worse than no profile.

The summary is a few hot frames rather than a flame graph: a flame graph is the
right way to explore a profile and the wrong thing to put in a terminal. The
profiler's own UI still does that.

## What is not in the pipeline

The resolver, the regex engine, the multiplexer and the parser combinators do
not participate, and are not pretended into it. They are the other tools you
write while building a language — resolving what to build against, matching
text, and a terminal to work in — and inventing a dependency between them and
the compiler would be a worse repository, not a more integrated one.

They share the registry, the CLI's module listing, and the test layout. That is
all they honestly share.

## Test layout

`pytest` from the root collects every module, which needs two things:

- **`--import-mode=importlib`**, because several modules ship their own `tests`
  package and the default mode resolves them all to one top-level name.
- **A root `conftest.py`** putting every module's source root on `sys.path`,
  including `modules/compiler/python`, which is one level deeper than its module
  folder.

For the same reason the WebAssembly runtime's test fixtures moved out of
`tests/fixtures.py` into `wasm_fixtures.py` at the module root: `tests.fixtures`
is ambiguous the moment more than one `tests` package is in play, and a
uniquely-named module is not.
