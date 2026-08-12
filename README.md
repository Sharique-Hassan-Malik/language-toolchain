# Developer Tools & Runtimes

Language and systems tooling built from scratch: a compiler, a WebAssembly runtime, a linear-time regex engine, a Reactive-Signals library, a spec-conformant Promise, a probabilistic cardinality estimator, a SAT-based dependency resolver, a sampling profiler, a terminal multiplexer, and a data scraper.

A collection of 10 self-contained projects. Each lives in its own subdirectory with its own `README.md` and `LICENSE` (most also include an `ARCHITECTURE.md` and a test suite), and can be built and run independently.

## Projects

| project | what it is |
|---|---|
| [`Dep_Resolver`](./Dep_Resolver) | A Python package dependency resolver that encodes the problem as a Boolean satisfiability (SAT) instance and solves it with a CDCL (Conflict-Driven… |
| [`HyperLogLog`](./HyperLogLog) | Count the number of distinct items in a stream to within about a percent, using a fixed 16 KB — no matter whether the stream had a thousand items o… |
| [`PPRA-Webscraper`](./PPRA-Webscraper) | Automated tool that scrapes the Public Procurement Regulatory Authority (PPRA) Pakistan website for ICT-sector tenders, downloads attached PDFs, ge… |
| [`Promises-APlus`](./Promises-APlus) | A JavaScript Promise built to the Promises/A+ specification, and verified against the official 872-test conformance suite — the same suite the spec… |
| [`Pyflame`](./Pyflame) | A sampling profiler that captures periodic call stack snapshots, aggregates them into a call tree and renders an interactive flame graph in the bro… |
| [`Reactive-Signals`](./Reactive-Signals) | Fine-grained reactivity from scratch — signal / computed / effect — with glitch-free, linear-time updates. |
| [`Regex-Engine`](./Regex-Engine) | A regular-expression engine that runs in time linear in the input length, for every pattern — including the patterns that make java.util.regex hang. |
| [`Termux`](./Termux) | A tmux-like terminal multiplexer in pure Python — split panes, multiple windows, scrollback buffer, copy mode and session persistence. |
| [`Toy-Compiler`](./Toy-Compiler) | A statically typed language implemented twice: once in Python and once in Rust. |
| [`WASM-Runtime`](./WASM-Runtime) | A pure-Python WebAssembly interpreter that parses the .wasm binary format, decodes every instruction and executes the complete MVP instruction set… |

## Repository layout

Each subdirectory is a standalone project; there is no shared build. Enter one and follow its README:

```bash
cd Dep_Resolver
cat README.md
```

## License

MIT — see the `LICENSE` file in each project.
