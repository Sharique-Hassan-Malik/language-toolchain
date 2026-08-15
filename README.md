# Language Toolchain

A statically-typed language, a WebAssembly runtime that executes it, a sampling
profiler that measures the runtime doing so, a SAT-based dependency resolver, a
regex engine, a terminal multiplexer, and a parser-combinator library.

The claim these make together is one sentence: **source goes in one end and
comes out running, and every stage in between is in this repository.**

```
lang modules                          # what is here, and how to run each alone
lang build prog.zap -o prog.wasm      # compile to WebAssembly
lang run prog.zap --compare           # execute, and check the VM agrees
lang run prog.zap --profile           # …and report where the runtime spent time
```

```
$ lang run modules/compiler/examples/factorial.zap --compare

  compile         18.21 ms   136 bytes of WebAssembly
  execute         11.82 ms   11 line(s) of output
  cross-check      1.14 ms   WebAssembly and the VM agree on 11 line(s)

  1
  1
  2
  6
  24
  ...
```

## The pipeline

```
   .zap  →  compiler  →  .wasm  →  wasm-runtime  →  output
                                        ↑
                                    profiler
```

The compiler gained a **WebAssembly backend** for this. It emits from the AST
rather than from the existing VM bytecode, and that is the whole design
decision: the bytecode is flat with signed jump offsets, WebAssembly has no
arbitrary jumps at all, and recovering structure from offsets is a
control-flow-graph problem when the structure is sitting right there in the AST.
`IfStmt` and `WhileStmt` map onto `if/else/end` and `block/loop/br_if` almost
directly.

The original stack VM stayed. `--compare` runs the same program on both backends
and checks they agree, which is the only real test that a second backend is
correct. Every example in the repository is checked both ways in CI.

## What building it found

Two things, both of which the modules could not have found alone:

**A bug in the WebAssembly runtime.** After an `if` block, the interpreter left
its instruction pointer *on* the block's `END` — and `END` breaks the dispatch
loop. Every instruction after an `if` was silently discarded, so a function
returned whatever it had computed before the branch. Nothing in the runtime's
own fixtures had code after an `if`; a compiler generating real programs found
it immediately. There is a regression test named after it.

**A performance finding about the runtime.** Profiling the interpreter while it
runs a recursive Zap program:

```
  profile — 58 samples, hottest frames:
    29.3%  _exec (executor.py:88)
    12.1%  _exec (executor.py:280)
     5.2%  _collect_if (executor.py:500)
```

`_collect_if` re-scans the block structure on every execution of an `if` rather
than caching it, which is 5% of runtime on a program whose inner loop is a
branch. It is a real, uncorrected finding — recorded rather than fixed, because
that is a change to the runtime's hot path and it wants its own benchmark.

Note what the profiler is showing: the *runtime's* frames, not the program's.
That is the right answer when you have written both, and the CLI says so rather
than letting it be misread.

## The seven modules

| Module | Language | What it is |
|---|---|---|
| [`compiler`](modules/compiler) | Python + Rust | The Zap language: lexer, parser, type checker, and two backends — a stack VM and WebAssembly. |
| [`wasm-runtime`](modules/wasm-runtime) | Python | Binary parser, validator and interpreter for WebAssembly modules. |
| [`profiler`](modules/profiler) | Python | Stack-sampling profiler with an interactive flame-graph UI. |
| [`resolver`](modules/resolver) | Python | Version-constraint resolution as SAT, with a CDCL solver that explains conflicts instead of guessing. |
| [`multiplexer`](modules/multiplexer) | Python | Split panes, windows, scrollback and session persistence over pseudoterminals. |
| [`regex`](modules/regex) | Java | Parser, NFA compiler and Pike VM — linear time on the patterns that hang backtracking engines. |
| [`parser-combinators`](modules/parser-combinators) | JavaScript | A combinator library with backtracking control and real error reporting. |

Three of the seven do not join the compile-and-run pipeline, and are not pretended
into it. They are the other tools you write when you are building a language:
resolving what to build against, matching text, and a terminal to work in.

## Using one module on its own

```bash
cd modules/compiler/python && python scripts/zapc.py ../examples/fibonacci.zap
cd modules/wasm-runtime    && python -c "from wasm.runtime import load_file"
cd modules/profiler        && python profile.py scripts/demo_workload.py
cd modules/resolver        && python resolve.py
cd modules/multiplexer     && python main.py
cd modules/regex           && ./build.sh && java -cp out regex.Main
cd modules/parser-combinators && npm test
```

Every Python module here runs on the standard library alone, so nothing needs
installing to try one.

## Install

```bash
pip install -e .
```

The regex engine needs a JDK and the parser combinators need Node; `lang modules`
reports which of those are missing rather than failing when you reach for them.

## Tests

```bash
pytest                     # everything, 257 tests
pytest modules/compiler    # one module
```

## Licence

MIT — see [LICENSE](LICENSE).
