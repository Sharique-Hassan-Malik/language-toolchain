# Regex Engine

> Part of the [Language Toolchain](../../README.md). Runs standalone from this
> folder; `lang` joins the compiler, runtime and profiler into one pipeline.

A regular-expression engine that runs in time **linear in the input length, for
every pattern** — including the patterns that make `java.util.regex` hang.

Written from scratch in Java: a recursive-descent parser, Thompson-construction
compiler, and a Pike virtual machine with submatch capture. No dependencies —
`javac` and `java` build and test the whole thing.

---

## Background

The regex most languages ship uses **backtracking**: it tries one way to match,
and on failure unwinds and tries the next. That is what makes backreferences and
lookahead possible — and it is why a pattern like `(.*a){15}` can be made to run
for seconds on a 30-character string. The number of ways to split the input
between the repetitions is exponential, and a backtracker explores all of them
before conceding there is no match. This is **ReDoS**: a denial of service you
trigger by choosing the input, not by volume.

This engine takes the other road. It advances *every* possible match
simultaneously, one character at a time, and merges paths that reconverge. There
is no exponential path count to explode, so a hostile input costs the same as a
friendly one.

---

## The headline

Same pattern, same inputs, same answer (no match). The only difference is the
work done to reach it.

```
pattern: /(.*a){15}$/   input: "a"*n + "!"  (defeats $, forcing a non-match)

   n       java.util.regex       this engine  ratio
----  --------------------  ----------------  -----
  15                 13 ms           0.26 ms  51x
  17                 44 ms           0.21 ms  206x
  19                 61 ms           0.50 ms  123x
  21                 83 ms           0.32 ms  264x
  23                276 ms           0.23 ms  1190x
  25               1085 ms           0.25 ms  4298x
  27               3705 ms           0.33 ms  11221x
  29     TIMEOUT (>4000ms)           0.81 ms  —
  31     TIMEOUT (>4000ms)           0.44 ms  —
```

`./build.sh` (or `java -cp out Redos`)

`java.util.regex` roughly doubles every two characters, hits seconds by n=27 and
times out by n=29. This engine holds a flat sub-millisecond line the whole way —
**over 11,000× faster** by n=27, and the gap widens without bound.

This is a difference in *complexity class*, not tuning. Modern
`java.util.regex` actually defuses the classic `(a+)+$` form, so the benchmark
uses a counted group it has not special-cased — but the underlying vulnerability
is the same, and it is structural.

## Why it cannot blow up

A backtracker explores paths one at a time. This engine keeps a set of *threads*
— one per reachable position in the compiled program — and steps them all
together per input character. Two threads that arrive at the same instruction
are identical from then on, so the duplicate is dropped:

```java
if (visited[pc] == gen) return;   // already reached this instruction this step
visited[pc] = gen;
```

Because the program has a fixed number of instructions, there are never more
than `program.length` live threads at any position. Total work is
`O(inputLength × programLength)` — linear in the input, for **any** pattern.
There is no path count to explode because reconverging paths are merged into one.

Greedy vs lazy, and the whole of leftmost-first semantics (`a|ab` on `"ab"`
matches `"a"`), fall out of thread *priority order* — no backtracking required.
See [ARCHITECTURE.md](./ARCHITECTURE.md).

## Correctness

The suite runs 21 groups of cases and, crucially, **9,600 differential checks
against `java.util.regex`**: for a dozen patterns using only features both
engines are specified to agree on, 400 random strings each are matched by both,
and any disagreement fails the build. Differential testing against a mature
reference finds parser and capture bugs that hand-written cases miss.

```
21 test methods, 9688 assertions, 0 failed
  note: 9600 differential checks against java.util.regex
```

## Usage

```bash
./build.sh                    # compile, test, benchmark — needs only a JDK

java -cp out regex.Main '(\d+)-(\d+)' 'ship 42-1000 now'
# match: "42-1000" at [5..12)
#   group 1: "42"
#   group 2: "1000"

java -cp out regex.Main --matches '^[a-z]+@[a-z]+\.[a-z]+$' 'user@example.com'   # true
java -cp out regex.Main --disasm '(a|b)*'                                        # the program
```

As a library:

```java
Regex r = Regex.compile("(\\d+)-(\\d+)");
Optional<Match> m = r.find("order 42-1000");
m.get().group(1);   // "42"

r.matches("42-1000");   // whole-string match
r.test("x 42-1000 y");  // matches somewhere
```

Supported: literals, `.`, `^`, `$`, `* + ?` (greedy and lazy), alternation `|`,
grouping and capture `( )`, character classes `[a-z] [^…]`, counted repetition
`{n} {n,} {n,m}`, and the escapes `\d \D \w \s \n \t \r`.

## What it does not do — on purpose

**No backreferences, no lookaround.** These are the features that *require*
backtracking, and matching a language with backreferences is NP-hard in general.
Their absence is not a gap; it is the reason linear time is possible. An engine
that offers them offers the ReDoS vulnerability with them.

Everything else a program needs from a regex — validation, tokenising,
extraction — this covers, in time an attacker cannot inflate.

## Layout

| file | role |
|---|---|
| `src/regex/Parser.java` | pattern text → AST, with counted-repetition unrolling |
| `src/regex/Ast.java` | the sealed node hierarchy |
| `src/regex/Program.java` | AST → instructions (Thompson construction) |
| `src/regex/Pike.java` | the linear-time VM with submatch capture |
| `src/regex/Regex.java` | the public API |
| `test/regex/RegexTest.java` | suite + zero-dependency runner + differential tests |
| `bench/Redos.java` | the headline benchmark |

## License

MIT
