# Architecture

## Pipeline

```
   pattern text
        │  Parser (recursive descent)
        ▼
      AST            sealed nodes: Lit, Dot, CharClass, Concat, Alt,
        │            Star, Plus, Quest, Group, anchors
        │  Program.compile (Thompson construction)
        ▼
   Program           a flat array of 9 instruction kinds
        │  Pike VM (thread set, lockstep, dedup by pc)
        ▼
   int[] captures  →  Match
```

Each stage does one thing. The parser knows what a pattern *means* and nothing
about execution; the compiler knows how to turn meaning into instructions and
nothing about parsing; the VM knows how to run instructions and nothing about
either. A grammar bug, a codegen bug and a matcher bug therefore live in three
different files, and the differential test tells you which.

## The instruction set

Nine opcodes, and the two that matter are the control-flow pair:

| op | meaning |
|---|---|
| `CHAR c` / `ANY` / `CLASS` | consume one input character if it matches |
| `MATCH` | accept |
| `JMP x` | branch to `x` (same input position) |
| `SPLIT x, y` | fork: try `x`, then `y` (same input position) |
| `SAVE n` | record the current position into capture slot `n` |
| `BOL` / `EOL` | assert start / end of input |

`SPLIT` is where a backtracker and this engine diverge. A backtracker, at a
choice point, tries one branch and *remembers the other to retry on failure* —
and the retries are what go exponential. Here, `SPLIT` simply queues both
branches as threads that run in parallel. There is nothing to retry.

## Compiling the quantifiers

Every quantifier is a loop built from `SPLIT` and `JMP`:

```
  star  := L1: split Body, End ; Body: <body> ; jmp L1 ; End:
  plus  := Body: <body> ; split Body, End ; End:
  quest := split Body, End ; Body: <body> ; End:
  alt   := split L1, L2 ; L1: <left> ; jmp End ; L2: <right> ; End:
```

**Greedy vs lazy is one bit: which `SPLIT` branch comes first.** A `SPLIT` tries
`x` before `y`, so greedy puts the body branch first ("match more, then try
stopping") and lazy puts the exit branch first. `a*` and `a*?` compile to the
same three instructions in the opposite order, and cost exactly the same to run.

**Counted repetition unrolls at compile time.** `x{3}` becomes three copies of
`x` concatenated; `x{2,4}` is two copies then two `x?`; `x{2,}` is two copies
then `x*`. The copies reuse the *same* AST subtree, so a group inside `(x){n}`
keeps its single index and reports the last iteration — matching
`java.util.regex`. A `MAX_REPEAT` cap rejects `a{2000}` at compile time, because
a program that cannot fit in memory is its own denial of service.

## The Pike VM

Two thread lists, `clist` (current position) and `nlist` (next), swapped each
step. A thread is a program counter plus its capture array.

```
seed a start thread at position 0
for sp = 0 .. inputLength:
    for each thread in clist, in priority order:
        CHAR/ANY/CLASS: if it matches input[sp], add pc+1 to nlist at sp+1
        MATCH:          record captures; abandon all lower-priority threads
    if unanchored and no match yet: seed a fresh start thread into nlist
    swap clist, nlist
```

Three details carry the whole design:

**Dedup by program counter is the linear-time guarantee.** `addThread` follows
all epsilon transitions (`JMP`, `SPLIT`, `SAVE`, assertions) and refuses to queue
a pc already reached this step. So a `SPLIT` whose branches reconverge adds one
thread, not two — and the live-thread count is capped at `program.length`
regardless of the pattern.

**MATCH abandons lower-priority threads, giving leftmost-first.** Threads are
ordered by priority (preferred `SPLIT` branch first). When one reaches `MATCH`,
every thread after it in the current step is discarded, because it had lower
priority and its match cannot win. That single rule produces greedy/lazy
behaviour and Perl-style alternation with no backtracking.

**Copy-on-save keeps forking cheap.** Threads share a capture array until one
executes `SAVE`, which clones before writing. A fork costs a reference copy, not
a full capture array, and a write never disturbs a sibling.

**Assertions are position-dependent epsilon transitions.** `BOL`/`EOL` are
evaluated inside `addThread` against the current position, so `^` proceeds only
at position 0 and `$` only at the end. The main loop runs one extra iteration at
`sp == inputLength` so that end-anchored threads and `MATCH` can fire with no
character to consume.

## Unanchored search stays leftmost

For `find`, a fresh start thread is seeded at each successive position — but only
until something matches, and always *appended last* so it has the lowest
priority. An earlier start therefore always outranks a later one, which makes the
returned match the leftmost. No `.*?` prefix, no second pass.

## Thread safety

A compiled `Regex` is immutable and safe to share. The `Pike` VM is not — it
owns a per-instruction scratch array — so each thread lazily gets its own VM over
the shared, immutable program via a `ThreadLocal`. Compile once, match from many
threads.

## What is deliberately absent

- **Backreferences and lookaround.** They require backtracking; matching a
  language with backreferences is NP-hard. Excluding them is what makes linear
  time possible, and is the entire security argument.
- **Unicode property classes** (`\p{...}`). The class machinery is code-point
  ranges and would extend cleanly; it is scope, not a design limit.
- **A DFA cache.** The Pike VM is already linear. A lazy DFA would lower the
  constant factor at the cost of submatch capture, which is the more useful
  feature to keep.
